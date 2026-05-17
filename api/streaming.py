"""
SSE streaming generator shared by /chat, /chat/regenerate, /chat/edit.

The async generator dereferences ``_runtime.graph`` at call time so it always
sees the singleton set by the lifespan handler — never a stale snapshot.

Yields SSE event types in order:
  - ``thought``       once per pipeline node when first reached
  - ``deep_search``   real-time status during multi-function parallel search
  - ``content``       LLM tokens from streamable nodes (after [NO_ANSWER] window)
  - ``content_replace`` overwrite partial tokens (retry / mid-stream error)
  - ``content_final`` post-processed final content (citations rebuilt)
  - ``final``         carries chat_id, message_id, ai_content, suggestive_actions
"""
import asyncio
import logging

from api import _runtime
from api.dependencies import _to_chip_code, sse_format
from infrastructure.cancel_signals.backend import consume_cancel

logger = logging.getLogger(__name__)


async def _stream_graph(state: dict, config: dict, thread_id: str):
    """Core streaming generator shared by /chat and /chat/regenerate.

    Yields SSE events: thought → content → final.
    Supports cancellation via the cancel-signal backend.
    """
    seen_nodes: set[str] = set()
    # Track function auto-selected by function_gate inside the sub-graph,
    # since aget_state on the parent graph may not reflect sub-graph changes.
    auto_selected_function: list[str] | None = None

    # ── Generate node streaming buffer ──
    # Buffer the first ~15 chars from generate to detect [NO_ANSWER] before
    # flushing tokens to the client. If detected, suppress all further tokens.
    generate_buffer: str = ""
    generate_aborted: bool = False
    generate_flushed: bool = False

    # ── Side-channel for real-time deep search status delivery ──
    # The parallel_search_node pushes status messages here as they
    # happen.  We drain the queue between graph chunks for near-real-time
    # delivery to the frontend (instead of batching at node completion).
    deep_search_queue: asyncio.Queue = asyncio.Queue()
    config["configurable"]["_deep_search_queue"] = deep_search_queue

    async for chunk in _runtime.graph.astream(
        state,
        config=config,
        stream_mode=["messages", "updates"],
        subgraphs=True,
    ):
        # ── Drain deep search queue (real-time status delivery) ──
        while not deep_search_queue.empty():
            try:
                status = deep_search_queue.get_nowait()
                # Pick icon based on step content
                if "Found" in status:
                    ds_icon = "check_circle"
                elif "Combining" in status:
                    ds_icon = "merge"
                elif "timed out" in status or "failed" in status:
                    ds_icon = "error_outline"
                elif "No results" in status:
                    ds_icon = "search_off"
                else:
                    ds_icon = "search"
                yield sse_format({
                    "type": "deep_search",
                    "content": status,
                    "node": "parallel_search",
                    "icon": ds_icon,
                })
            except asyncio.QueueEmpty:
                break
        # ── Check cancellation ──
        if consume_cancel(thread_id):
            yield sse_format({"type": "final", "cancelled": True})
            return

        namespace, mode, data = chunk

        if mode == "updates":
            for node in data.keys():
                node_data = data.get(node, {})

                # Capture function auto-selected by function_gate
                if node == "function_gate" and node_data.get("function"):
                    auto_selected_function = node_data["function"]
                    logger.info("function_gate auto-selected: %s", auto_selected_function)

                # Reset streaming state so the second generate pass (after
                # doc-fallback) is treated as a fresh streaming run.
                if node == "set_doc_fallback":
                    generate_buffer = ""
                    generate_aborted = False
                    generate_flushed = False
                    seen_nodes.discard("generate")

                if node and node not in seen_nodes:
                    seen_nodes.add(node)
                    thought_entry = _runtime.NODE_THOUGHT.get(node)
                    if thought_entry:
                        display_name = thought_entry["display"]
                        message = thought_entry["message"]
                    else:
                        display_name, message = node, f"Processing {node}..."
                    logger.debug("thought (updates) node=%s", node)
                    yield sse_format({
                        "type": "thought",
                        "node": display_name,
                        "message": message,
                        "group": thought_entry.get("group", "") if thought_entry else "",
                        "icon": thought_entry.get("icon", "settings") if thought_entry else "settings",
                    })

                    # ── Supervisor RESPOND prose delivery ──
                    # Supervisor uses with_structured_output so its LLM tokens
                    # are JSON fragments (not prose). When next==RESPOND, the
                    # completed update contains ai_content with the actual reply.
                    # Deliver it as a single content event via "updates" mode.
                    if node == "Supervisor":
                        respond_content = node_data.get("ai_content")
                        if respond_content:
                            yield sse_format({
                                "type": "content",
                                "content": respond_content,
                                "node": "Supervisor",
                            })

                # ── Generate node completion (runs regardless of seen_nodes) ──
                # This fires when generate_node returns its state update.
                # Messages-mode tokens already streamed in real-time; here we
                # handle buffer flush, retry delivery, and citation reconciliation.
                if node == "generate":
                    # Flush any remaining buffer from messages mode
                    if generate_buffer and not generate_aborted and not generate_flushed:
                        yield sse_format({
                            "type": "content",
                            "content": generate_buffer,
                            "node": "generate",
                        })
                        generate_buffer = ""
                        generate_flushed = True

                    gen_content = node_data.get("ai_content")
                    gen_error = node_data.get("error_info")

                    if gen_error and gen_content:
                        # Mid-stream LLM failure — _safe_node returned the
                        # error message. Force content_replace so any partial
                        # tokens already streamed get overwritten in the UI.
                        yield sse_format({
                            "type": "content_replace",
                            "content": gen_content,
                            "node": "generate",
                        })
                    elif generate_aborted and gen_content:
                        # Retry path — send full replacement content
                        yield sse_format({
                            "type": "content_replace",
                            "content": gen_content,
                            "node": "generate",
                        })
                    elif generate_flushed and gen_content:
                        # Normal path — send final post-processed content
                        # (citations rebuilt deterministically). The frontend
                        # should replace the streamed content with this.
                        yield sse_format({
                            "type": "content_final",
                            "content": gen_content,
                            "node": "generate",
                        })
                    elif gen_content:
                        # No tokens flushed yet (early failure / fallback path)
                        # — deliver as a single content event.
                        yield sse_format({
                            "type": "content",
                            "content": gen_content,
                            "node": "generate",
                        })

                # ── Agent format node completion (LMS, Expense, Scorecard) ──
                # These nodes stream tokens via messages mode (they are in
                # STREAMABLE_NODES). On completion, send content_final so the
                # frontend replaces streamed tokens with the final version,
                # preventing duplication with the ai_content in the final event.
                if node in ("lms_format", "expense_format", "scorecard_format"):
                    fmt_content = node_data.get("ai_content")
                    if fmt_content:
                        yield sse_format({
                            "type": "content_final",
                            "content": fmt_content,
                            "node": node,
                        })

                # ── Multi-function search: thought event for deep search ──
                # Status messages are delivered in real-time via the
                # asyncio.Queue side-channel (drained at the top of this loop).
                # Nothing to emit here from updates mode.

        elif mode == "messages":
            chunk_msg, metadata = data
            node = metadata.get("langgraph_node")
            logger.debug("Streaming chunk from node=%s content=%r", node, chunk_msg.content)

            if node and node not in seen_nodes:
                seen_nodes.add(node)
                thought_entry = _runtime.NODE_THOUGHT.get(node)
                if thought_entry:
                    display_name = thought_entry["display"]
                    message = thought_entry["message"]
                else:
                    display_name, message = node, f"Processing {node}..."
                yield sse_format({
                    "type": "thought",
                    "node": display_name,
                    "message": message,
                    "group": thought_entry.get("group", "") if thought_entry else "",
                    "icon": thought_entry.get("icon", "settings") if thought_entry else "settings",
                })

            if chunk_msg.content and node in _runtime.STREAMABLE_NODES:
                # For generate node: suppress [NO_ANSWER] token fragments.
                # The generate_node aborts after detecting [NO_ANSWER] (~12 chars),
                # but a few leading tokens may have already been emitted by LangGraph.
                # Buffer them and only flush once we're past the detection window.
                if node == "generate":
                    generate_buffer += chunk_msg.content
                    if len(generate_buffer) < 15:
                        continue  # still in detection window
                    if generate_buffer.strip().startswith("[NO_ANSWER]"):
                        # Abort — don't send anything; retry will use content_replace
                        generate_buffer = ""
                        generate_aborted = True
                        continue
                    if generate_aborted:
                        continue  # stream was aborted, ignore remaining chunks
                    # First flush: send accumulated buffer
                    if generate_buffer and not generate_flushed:
                        generate_flushed = True
                        yield sse_format({"type": "content", "content": generate_buffer, "node": node})
                        generate_buffer = ""
                    else:
                        yield sse_format({"type": "content", "content": chunk_msg.content, "node": node})
                else:
                    yield sse_format({"type": "content", "content": chunk_msg.content, "node": node})

    # ── Drain any remaining deep search status messages ──
    while not deep_search_queue.empty():
        try:
            status = deep_search_queue.get_nowait()
            if "Found" in status:
                ds_icon = "check_circle"
            elif "Combining" in status:
                ds_icon = "merge"
            elif "timed out" in status or "failed" in status:
                ds_icon = "error_outline"
            elif "No results" in status:
                ds_icon = "search_off"
            else:
                ds_icon = "search"
            yield sse_format({
                "type": "deep_search",
                "content": status,
                "node": "parallel_search",
                "icon": ds_icon,
            })
        except asyncio.QueueEmpty:
            break

    # ── Final event ──
    try:
        state_snapshot = await _runtime.graph.aget_state(config)
        if state_snapshot:
            final_state = state_snapshot.values
            logger.info(
                "Final state: function=%s, functions_found=%s, requires_function_selection=%s",
                final_state.get("function"),
                final_state.get("functions_found"),
                final_state.get("requires_function_selection"),
            )
            raw_actions = final_state.get("suggestive_actions") or []
            actions = []
            for a in raw_actions:
                if hasattr(a, "model_dump"):
                    actions.append(a.model_dump())
                elif isinstance(a, dict):
                    actions.append(a)
                else:
                    actions.append({"short_title": str(a)})
            yield sse_format({
                "type": "final",
                "chat_id": final_state.get("chat_id"),
                "message_id": final_state.get("message_id"),
                "ai_content": final_state.get("ai_content", []),
                "suggestive_actions": actions,
                "conversation_title": final_state.get("conversation_title"),
                "requires_function_selection": bool(
                    final_state.get("requires_function_selection")
                ),
                "function_required_reason": final_state.get(
                    "function_required_reason"
                ),
                "function_hint": final_state.get("function_hint"),
                "function_candidates": final_state.get("functions_found") or [],
                "selected_function": _to_chip_code(
                    (
                        final_state.get("function")
                        or auto_selected_function
                        or [None]
                    )[0]
                ),
            })
    except Exception as exc:
        logger.error("Failed to emit final SSE event: %s", exc, exc_info=True)
