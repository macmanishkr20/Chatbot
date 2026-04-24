"""Bridge a finalised voice transcript into the existing LangGraph RAG.

The screenshare feature intentionally does **not** rebuild any of the
chat plumbing. Once the Realtime WS produces a final user transcript, we
feed it into the same compiled graph that the REST ``/chat`` endpoint
uses. That way:

  • The ``checkpointer`` stores the turn against the same ``thread_id``
    (``{user_id}_{chat_session_id}``) — so edit / regenerate / resume
    continue to work.
  • The ``memory`` node writes to the long-term store.
  • The ``persist`` node writes the user+assistant pair to SQL
    (``SQLChatClient``) exactly as typed messages do.
  • Title generation, suggestive actions, and citations behave normally.

As the graph streams, we mirror its output onto the session's event
queue as control-WS events so the frontend can render the assistant
message live in the chat window. When TTS is configured, the final
assistant text is also spoken back through the outbound WebRTC track.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage

from graph.context_manager import trim_messages_to_budget
from graph.nodes.supervisor import get_graph
from screenshare.tts_synthesizer import synthesize

if TYPE_CHECKING:  # pragma: no cover
    from screenshare.session import ScreenShareSession
    from screenshare.tts_track import TTSAudioTrack

logger = logging.getLogger(__name__)

# Nodes whose streamed tokens correspond to user-facing prose — mirrors
# the set used by ``app._STREAMABLE_NODES``.
_STREAMABLE_NODES = frozenset({"generate", "search"})


def _ensure_base_messages(messages):
    """Best-effort reconstruction from checkpoint-deserialised payloads.

    Kept as a local helper (rather than importing from ``app``) so this
    module has no dependency on the FastAPI entry point — that would
    create an import cycle when ``app.py`` registers our router.
    """
    from langchain_core.messages import AIMessage, BaseMessage
    import re

    result = []
    for m in messages:
        if isinstance(m, BaseMessage):
            result.append(m)
            continue
        if isinstance(m, dict):
            role = (m.get("type") or m.get("role") or "").lower()
            content = m.get("content", "")
            result.append(
                HumanMessage(content=content)
                if role in ("human", "user")
                else AIMessage(content=content)
            )
            continue
        if isinstance(m, str):
            is_human = m.startswith("HumanMessage") or bool(
                re.search(r"type=['\"]human['\"]", m)
            )
            cm = re.search(r"content='((?:[^'\\]|\\.)*)'", m) or re.search(
                r'content="((?:[^"\\]|\\.)*)"', m
            )
            content = cm.group(1) if cm else ""
            result.append(
                HumanMessage(content=content)
                if is_human
                else AIMessage(content=content)
            )
    return result


async def _build_state(session: "ScreenShareSession", user_input: str, graph) -> dict:
    """Reconstruct a RAGState dict from the checkpoint, same as ``/chat``."""
    thread_id = f"{session.user_id}_{session.chat_session_id}"
    config = {"configurable": {"thread_id": thread_id}}

    current_state = None
    try:
        ckpt = await graph.checkpointer.aget(config)
        if ckpt:
            current_state = ckpt.get("channel_values", {})
    except Exception as exc:
        logger.debug("screenshare.bridge: no prior checkpoint (%s)", exc)

    if current_state and current_state.get("messages"):
        current_state["messages"] = _ensure_base_messages(
            current_state["messages"]
        )
        current_state["messages"] = trim_messages_to_budget(
            current_state["messages"]
        )
        current_state["messages"].append(HumanMessage(content=user_input))
        current_state["user_input"] = user_input
        current_state["chat_session_id"] = session.chat_session_id
        current_state["function"] = session.function
        current_state["sub_function"] = session.sub_function
        current_state["source_url"] = session.source_url
        current_state["start_date"] = session.start_date
        current_state["end_date"] = session.end_date
        current_state["is_free_form"] = session.is_free_form
        current_state["input_type"] = "ask"
        # Reset per-turn transient fields (preserve citation_map).
        current_state["events"] = []
        current_state["error_info"] = None
        current_state["ai_content"] = None
        current_state["prompt_used"] = None
        current_state["response"] = None
        current_state["suggestive_actions"] = None
        current_state["conversation_title"] = None
        state = current_state
    else:
        state = {
            "messages": [HumanMessage(content=user_input)],
            "input_type": "ask",
            "user_input": user_input,
            "is_free_form": session.is_free_form,
            "user_id": session.user_id,
            "chat_session_id": session.chat_session_id,
            "function": session.function,
            "sub_function": session.sub_function,
            "source_url": session.source_url,
            "start_date": session.start_date,
            "end_date": session.end_date,
            "preferred_language": session.preferred_language,
        }
    return state, config, thread_id


async def bridge_transcript_to_graph(
    session: "ScreenShareSession",
    user_input: str,
    tts_track: "TTSAudioTrack | None" = None,
) -> None:
    """Run ``user_input`` through the LangGraph pipeline and surface the reply.

    Safe to invoke concurrently — a per-session lock serialises turns so
    checkpoint reads/writes don't race.
    """
    async with session._bridge_lock:
        if session._is_bridging:
            logger.warning(
                "screenshare.bridge: prior turn still running for session=%s; "
                "skipping duplicate transcript event",
                session.id,
            )
            return
        session._is_bridging = True

    try:
        graph = await get_graph()
        state, config, _thread_id = await _build_state(session, user_input, graph)

        await session.emit(type="speaking", state="start", role="assistant")

        assistant_text_parts: list[str] = []
        supervisor_text: str | None = None

        async for chunk in graph.astream(
            state,
            config=config,
            stream_mode=["messages", "updates"],
            subgraphs=True,
        ):
            _ns, mode, data = chunk

            if mode == "updates":
                # The Supervisor sometimes returns its reply as a single
                # ``ai_content`` field (see ``app._stream_graph``). Capture
                # it so we always have something to speak + persist.
                if "Supervisor" in data:
                    respond = (data.get("Supervisor") or {}).get("ai_content")
                    if respond:
                        supervisor_text = respond
                        await session.emit(
                            type="assistant",
                            text=respond,
                            final=False,
                            node="Supervisor",
                        )

            elif mode == "messages":
                chunk_msg, metadata = data
                node = metadata.get("langgraph_node")
                if (
                    chunk_msg.content
                    and node in _STREAMABLE_NODES
                ):
                    assistant_text_parts.append(chunk_msg.content)
                    await session.emit(
                        type="assistant",
                        text=chunk_msg.content,
                        final=False,
                        node=node,
                    )

        # Assemble the final assistant text.
        final_text = "".join(assistant_text_parts).strip() or (supervisor_text or "")

        # Pull the final state so we can emit the same shape /chat emits.
        chat_id = None
        message_id = None
        ai_content = None
        suggestive_actions: list = []
        conversation_title = None
        try:
            snap = await graph.aget_state(config)
            if snap:
                fs = snap.values
                chat_id = fs.get("chat_id")
                message_id = fs.get("message_id")
                ai_content = fs.get("ai_content")
                conversation_title = fs.get("conversation_title")
                raw_actions = fs.get("suggestive_actions") or []
                for a in raw_actions:
                    if hasattr(a, "model_dump"):
                        suggestive_actions.append(a.model_dump())
                    elif isinstance(a, dict):
                        suggestive_actions.append(a)
                    else:
                        suggestive_actions.append({"short_title": str(a)})
                # Fall back to persisted ai_content string when streaming
                # produced nothing (e.g. structured-output-only paths).
                if not final_text and isinstance(ai_content, str):
                    final_text = ai_content
        except Exception as exc:
            logger.error(
                "screenshare.bridge: failed to read final state: %s", exc
            )

        await session.emit(
            type="assistant",
            text=final_text,
            final=True,
        )
        await session.emit(
            type="final",
            chat_id=chat_id,
            message_id=message_id,
            ai_content=ai_content,
            suggestive_actions=suggestive_actions,
            conversation_title=conversation_title,
        )
        await session.emit(type="speaking", state="end", role="assistant")

        # Speak the reply via TTS (no-op when Azure Speech isn't configured).
        if tts_track is not None and final_text:
            try:
                async for pcm in synthesize(final_text):
                    await tts_track.push(pcm)
            except Exception as exc:  # pragma: no cover
                logger.exception("screenshare.bridge: TTS failed: %s", exc)

    except Exception as exc:
        logger.exception("screenshare.bridge: graph run failed: %s", exc)
        await session.emit(
            type="error", message=f"Assistant pipeline failed: {exc}"
        )
    finally:
        session._is_bridging = False
