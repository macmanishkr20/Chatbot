"""
Export-document node.

When the supervisor routes here, this node:
  1. Determines the requested format from state (export_format) or user
     intent if missing.
  2. If the format requires a template (PPT/Keynote) and none was
     uploaded, returns a friendly message asking the user to upload a
     template — surfaced to the UI as ``template_request`` so the
     frontend can render an inline upload widget.
  3. Otherwise asks the LLM to plan the document content (title, sections,
     slides) in JSON, then calls the right generator to write the file
     under ``./generated_docs/{file_id}.{ext}`` and returns a download
     URL via the final SSE event.

The node is intentionally self-contained — no SearchClient calls — so
the supervisor can route both knowledge-base questions (rag_graph) and
document-export requests (export_document) from the same conversation.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import AzureChatOpenAI

from config import (
    AZURE_OPENAI_CHAT_API_VERSION,
    AZURE_OPENAI_ENDPOINT,
    AZURE_OPENAI_KEY,
    AZURE_OPENAI_TEMPERATURE,
)
from graph.state import RAGState
from prompts.export_prompt import EXPORT_PLAN_SYSTEM_PROMPT, format_planner_user_prompt
from services.openai_client import get_llm_model
from tools.export_generators import resolve_format

logger = logging.getLogger(__name__)


# Where generated documents and uploaded templates live on disk.
# Resolved at module import so paths are stable across worker restarts.
_REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATED_DIR = _REPO_ROOT / "generated_docs"
TEMPLATE_DIR = _REPO_ROOT / "uploaded_templates"
GENERATED_DIR.mkdir(parents=True, exist_ok=True)
TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)


# Map raw user words → canonical format keys understood by the registry.
_FORMAT_KEYWORDS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(power\s*point|powerpoint|ppt|pptx|slide\s*deck|deck|presentation)\b", re.I), "pptx"),
    (re.compile(r"\b(keynote)\b", re.I), "keynote"),
    (re.compile(r"\b(excel|xlsx|spreadsheet|workbook)\b", re.I), "xlsx"),
    (re.compile(r"\b(numbers)\b", re.I), "numbers"),
    (re.compile(r"\b(word|docx|document)\b", re.I), "docx"),
    (re.compile(r"\b(pages)\b", re.I), "pages"),
    (re.compile(r"\b(json)\b", re.I), "json"),
    (re.compile(r"\b(text\s*file|txt|plain\s*text)\b", re.I), "txt"),
]


def _detect_format(user_input: str) -> str | None:
    for pattern, key in _FORMAT_KEYWORDS:
        if pattern.search(user_input):
            return key
    return None


def _extract_json(text: str) -> dict | None:
    """Best-effort JSON extraction from an LLM response."""
    if not text:
        return None
    # Strip markdown fences
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return None
    return None


def _get_planner_llm() -> AzureChatOpenAI:
    return AzureChatOpenAI(
        azure_deployment=get_llm_model("events"),
        api_key=AZURE_OPENAI_KEY,
        api_version=AZURE_OPENAI_CHAT_API_VERSION,
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        temperature=AZURE_OPENAI_TEMPERATURE,
        max_retries=2,
        streaming=False,
    )


async def export_node(state: RAGState) -> dict:
    user_input = state.get("user_input", "") or ""
    requested_format = (state.get("export_format") or "").strip().lower()
    template_file_id = state.get("template_file_id")

    fmt_key = requested_format or _detect_format(user_input) or "docx"
    spec = resolve_format(fmt_key)
    if not spec:
        msg = f"Sorry, I can't export to **{fmt_key}** yet. Supported: PowerPoint, Excel, Word, TXT, JSON, Pages, Numbers, Keynote."
        return {
            "ai_content": msg,
            "messages": [AIMessage(content=msg)],
            "is_free_form": True,
        }

    extension, requires_template, generator, ios_note = spec

    # ── Template handling ──
    template_path: Path | None = None
    if template_file_id:
        candidate = TEMPLATE_DIR / f"{template_file_id}.{extension}"
        if candidate.exists():
            template_path = candidate
        else:
            # Allow the upload to have any of the supported template extensions
            for ext_try in (extension, "pptx", "docx", "xlsx"):
                p = TEMPLATE_DIR / f"{template_file_id}.{ext_try}"
                if p.exists():
                    template_path = p
                    break

    if requires_template and template_path is None:
        ask = (
            f"To create a high-quality **{fmt_key.upper()}** in EY enterprise style, "
            f"please upload a `.{extension}` template using the upload button below. "
            f"I'll edit your template directly so the deck inherits its master slide, "
            f"theme, fonts, and branding."
        )
        return {
            "ai_content": ask,
            "messages": [AIMessage(content=ask)],
            "is_free_form": True,
            "export_format": fmt_key,
            "template_request": {
                "format": fmt_key,
                "extension": extension,
                "topic": user_input,
            },
        }

    # ── Plan content via LLM ──
    llm = _get_planner_llm()
    planner_messages = [
        SystemMessage(content=EXPORT_PLAN_SYSTEM_PROMPT),
        HumanMessage(content=format_planner_user_prompt(
            fmt_key=fmt_key,
            extension=extension,
            user_request=user_input,
            preferred_language=state.get("preferred_language") or "English",
        )),
    ]

    try:
        plan_response = await llm.ainvoke(planner_messages)
    except Exception as e:
        logger.error("export_node: planner LLM failed: %s", e, exc_info=True)
        err = "I couldn't generate the document content. Please try again."
        return {"ai_content": err, "messages": [AIMessage(content=err)], "is_free_form": True}

    plan = _extract_json(plan_response.content) or {}
    if not plan.get("title"):
        plan["title"] = user_input[:80] or "Document"

    # ── Generate file ──
    file_id = uuid.uuid4().hex
    output_path = GENERATED_DIR / f"{file_id}.{extension}"
    try:
        generator(output_path, plan, template_path)
    except Exception as e:
        logger.error("export_node: generator failed for %s: %s", fmt_key, e, exc_info=True)
        err = f"I couldn't build the {fmt_key.upper()} file: {e}"
        return {"ai_content": err, "messages": [AIMessage(content=err)], "is_free_form": True}

    title = plan.get("title", "Document")
    safe_title = re.sub(r"[^A-Za-z0-9 _-]+", "", title).strip().replace(" ", "_") or "document"
    download_filename = f"{safe_title}.{extension}"

    summary_parts = [f"I've prepared **{title}** as a `.{extension}` file."]
    if ios_note:
        summary_parts.append(ios_note)
    summary_parts.append("Click the download button below to save it.")
    ai_content = "\n\n".join(summary_parts)

    return {
        "ai_content": ai_content,
        "messages": [AIMessage(content=ai_content)],
        "is_free_form": True,
        "export_format": fmt_key,
        "download": {
            "file_id": file_id,
            "filename": download_filename,
            "extension": extension,
            "format": fmt_key,
            "url": f"/download/{file_id}.{extension}",
            "ios_note": ios_note,
        },
    }
