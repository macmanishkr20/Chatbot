"""
Document export service — standalone from the chat / LangGraph pipeline.

Two scopes:
  - message      : export a single assistant message as Word/Excel/TXT/JSON.
  - conversation : export the entire chat transcript. PPT (and Keynote)
                   summarise the conversation into a slide deck; Word/Excel
                   render it as a transcript or structured table.

PPT/Keynote require an uploaded template (mandatory). Word/Excel/TXT/JSON
accept an optional template (Word & Excel only — TXT/JSON ignore it).

The planner LLM produces the same JSON schemas the generators consume
(see prompts.export_prompt). A direct fallback is used for TXT/JSON to
avoid an unnecessary model call when the content is just plain text.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from pathlib import Path
from typing import Any, Iterable

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import AzureChatOpenAI

from config import (
    AZURE_OPENAI_CHAT_API_VERSION,
    AZURE_OPENAI_ENDPOINT,
    AZURE_OPENAI_KEY,
    AZURE_OPENAI_TEMPERATURE,
)
from prompts.export_prompt import EXPORT_PLAN_SYSTEM_PROMPT, format_planner_user_prompt
from services.openai_client import get_llm_model
from tools.export_generators import resolve_format

logger = logging.getLogger(__name__)


_REPO_ROOT = Path(__file__).resolve().parents[1]
GENERATED_DIR = _REPO_ROOT / "generated_docs"
TEMPLATE_DIR = _REPO_ROOT / "uploaded_templates"
GENERATED_DIR.mkdir(parents=True, exist_ok=True)
TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)


class ExportError(Exception):
    """Raised for user-facing export failures (turned into HTTP 4xx)."""


def _planner_llm() -> AzureChatOpenAI:
    return AzureChatOpenAI(
        azure_deployment=get_llm_model("events"),
        api_key=AZURE_OPENAI_KEY,
        api_version=AZURE_OPENAI_CHAT_API_VERSION,
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        temperature=AZURE_OPENAI_TEMPERATURE,
        max_retries=2,
        streaming=False,
    )


def _extract_json(text: str) -> dict | None:
    if not text:
        return None
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


def _safe_filename(title: str, extension: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9 _-]+", "", title or "").strip().replace(" ", "_")
    return f"{cleaned or 'document'}.{extension}"


def _resolve_template(template_file_id: str | None, extension: str) -> Path | None:
    if not template_file_id:
        return None
    if not re.match(r"^[A-Za-z0-9_-]+$", template_file_id):
        raise ExportError("Invalid template_file_id")
    # The uploaded template's extension may differ from the output extension
    # (e.g. user uploads .docx but we still output .docx — same; but a .pptx
    # template only ever produces .pptx). Try the output extension first,
    # then the common Office types.
    for ext_try in (extension, "pptx", "docx", "xlsx"):
        p = TEMPLATE_DIR / f"{template_file_id}.{ext_try}"
        if p.exists():
            return p
    raise ExportError("Uploaded template not found — please upload again.")


def _render_transcript(messages: Iterable[dict[str, Any]]) -> str:
    """Render the conversation as plain text for the planner."""
    lines: list[str] = []
    for m in messages:
        role = (m.get("role") or "").upper() or "MESSAGE"
        content = (m.get("content") or "").strip()
        if not content:
            continue
        lines.append(f"{role}:\n{content}\n")
    return "\n".join(lines).strip()


def _build_planner_request(
    fmt_key: str,
    extension: str,
    scope: str,
    content: str,
    title: str | None,
    preferred_language: str,
) -> str:
    intro: str
    if scope == "conversation":
        if fmt_key in ("pptx", "keynote"):
            intro = (
                "Summarise the following EY MENA chat conversation into a "
                "professional, enterprise slide deck. Capture the user's questions "
                "and the assistant's findings as themes, organised under clear "
                "section headings. Use crisp, client-ready language. Do not include "
                "raw 'USER:' / 'ASSISTANT:' lines in the deck."
            )
        elif fmt_key in ("xlsx", "numbers"):
            intro = (
                "Convert the following chat conversation into a structured workbook. "
                "Where the assistant's answers contain enumerable items (policies, "
                "steps, functions), put them into appropriate sheets with headers. "
                "Otherwise produce a 'Q&A' sheet with columns: # | Question | Answer."
            )
        else:
            intro = (
                "Render the following EY MENA chat conversation as a polished "
                "transcript document with section headings per topic. Use the "
                "user's questions to derive headings; place the assistant's "
                "answers as paragraphs/bullets underneath."
            )
    else:
        intro = (
            "Convert the following assistant message into a "
            f"professional, enterprise-quality {fmt_key.upper()} document. "
            "Preserve all factual content; reorganise into the required schema. "
            "Do not invent new facts."
        )

    suggested_title = title or ("Conversation summary" if scope == "conversation" else "Assistant response")

    return (
        f"{intro}\n\n"
        f"Suggested title: {suggested_title}\n"
        f"Output language: {preferred_language}\n"
        f"---\n"
        f"{content}\n"
        f"---\n\n"
        + format_planner_user_prompt(
            fmt_key=fmt_key,
            extension=extension,
            user_request="(use the content above)",
            preferred_language=preferred_language,
        )
    )


def _build_direct_plan(scope: str, content: str, title: str | None, messages: list[dict] | None) -> dict:
    """Schema-shaped plan for TXT/JSON without an LLM call."""
    deck_title = title or ("Conversation transcript" if scope == "conversation" else "Assistant response")
    if scope == "conversation" and messages:
        sections = []
        for m in messages:
            role = (m.get("role") or "").lower()
            text = (m.get("content") or "").strip()
            if not text:
                continue
            sections.append({
                "heading": "User" if role == "user" else "Assistant",
                "paragraphs": [text],
            })
        return {"title": deck_title, "sections": sections}
    return {
        "title": deck_title,
        "sections": [{"heading": "Content", "paragraphs": [content or ""]}],
    }


async def run_export(
    *,
    user_id: str,
    fmt: str,
    scope: str,
    content: str | None,
    messages: list[dict] | None,
    template_file_id: str | None,
    title: str | None,
    preferred_language: str = "English",
) -> dict:
    """Produce one document and return ``{url, filename, ios_note, file_id}``."""
    fmt_key = (fmt or "").strip().lower()
    spec = resolve_format(fmt_key)
    if not spec:
        raise ExportError(f"Unsupported format: {fmt}")

    extension, requires_template, generator, ios_note = spec

    if scope not in ("message", "conversation"):
        raise ExportError("scope must be 'message' or 'conversation'")

    if scope == "message":
        if not (content or "").strip():
            raise ExportError("content is required for scope='message'")
        rendered = content or ""
    else:
        if not messages:
            raise ExportError("messages is required for scope='conversation'")
        rendered = _render_transcript(messages)
        if not rendered:
            raise ExportError("Conversation has no content to export")

    template_path = _resolve_template(template_file_id, extension)
    if requires_template and template_path is None:
        raise ExportError(
            f"A .{extension} template is required for {fmt_key.upper()} exports. "
            "Upload one via /upload-template and pass template_file_id."
        )

    # Build the document plan
    if fmt_key in ("txt", "json"):
        plan = _build_direct_plan(scope, rendered, title, messages)
    else:
        llm = _planner_llm()
        try:
            response = await llm.ainvoke([
                SystemMessage(content=EXPORT_PLAN_SYSTEM_PROMPT),
                HumanMessage(content=_build_planner_request(
                    fmt_key=fmt_key,
                    extension=extension,
                    scope=scope,
                    content=rendered,
                    title=title,
                    preferred_language=preferred_language,
                )),
            ])
        except Exception as e:
            logger.error("export planner failed: %s", e, exc_info=True)
            raise ExportError("Failed to plan the document. Please try again.")
        plan = _extract_json(response.content) or {}

    if not plan.get("title"):
        plan["title"] = title or ("Conversation summary" if scope == "conversation" else "Assistant response")

    # Generate file
    file_id = uuid.uuid4().hex
    output_path = GENERATED_DIR / f"{file_id}.{extension}"
    try:
        generator(output_path, plan, template_path)
    except Exception as e:
        logger.error("export generator failed for %s: %s", fmt_key, e, exc_info=True)
        raise ExportError(f"Failed to build the {fmt_key.upper()} file: {e}")

    return {
        "file_id": file_id,
        "url": f"/download/{file_id}.{extension}",
        "filename": _safe_filename(plan.get("title", title or ""), extension),
        "extension": extension,
        "format": fmt_key,
        "ios_note": ios_note,
    }
