"""Plain text and JSON generators."""
from __future__ import annotations

import json as _json
from pathlib import Path
from typing import Any


def build_txt(
    output_path: Path,
    plan: dict[str, Any],
    template_path: Path | None = None,  # unused
) -> Path:
    """Render the plan as a clean, readable text document."""
    title = plan.get("title") or "Document"
    subtitle = plan.get("subtitle") or ""

    lines: list[str] = [title, "=" * len(title), ""]
    if subtitle:
        lines.extend([subtitle, ""])

    for section in plan.get("sections") or []:
        heading = section.get("heading") or ""
        if heading:
            lines.extend([heading, "-" * len(heading), ""])
        for para in section.get("paragraphs") or []:
            lines.extend([para, ""])
        for bullet in section.get("bullets") or []:
            lines.append(f"  • {bullet}")
        if section.get("bullets"):
            lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


def build_json(
    output_path: Path,
    plan: dict[str, Any],
    template_path: Path | None = None,  # unused
) -> Path:
    """Serialize the plan as pretty-printed JSON."""
    output_path.write_text(_json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    return output_path
