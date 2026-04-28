"""
Document export generators.

Each generator builds a single output file from an LLM-produced content
plan and returns the absolute path on disk. The registry below maps a
canonical format key to its generator function.

Format keys cover both the requested Windows formats (xlsx, pptx, docx,
txt, json) and macOS iWork formats (pages, numbers, keynote). iWork
files are proprietary — there is no cross-platform Python library for
them — so we generate the equivalent Office format and let the user
open & re-save in iWork. The download payload includes a hint to the
end user.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from tools.export_generators.excel_generator import build_excel
from tools.export_generators.pptx_generator import build_pptx
from tools.export_generators.docx_generator import build_docx
from tools.export_generators.text_generator import build_txt, build_json


# (extension, requires_template, generator, ios_note)
FormatSpec = tuple[str, bool, Callable[..., Path], str | None]

FORMAT_REGISTRY: dict[str, FormatSpec] = {
    "xlsx":    ("xlsx", False, build_excel, None),
    "pptx":    ("pptx", True,  build_pptx, None),
    "docx":    ("docx", False, build_docx, None),
    "txt":     ("txt",  False, build_txt,  None),
    "json":    ("json", False, build_json, None),
    # iWork — generate Office equivalents
    "pages":   ("docx", False, build_docx, "Open this file in Pages and choose File → Save As to convert to .pages."),
    "numbers": ("xlsx", False, build_excel, "Open this file in Numbers and choose File → Save As to convert to .numbers."),
    "keynote": ("pptx", True,  build_pptx, "Open this file in Keynote and choose File → Save As to convert to .key."),
}


def resolve_format(fmt: str) -> FormatSpec | None:
    """Lookup a format spec; case-insensitive."""
    if not fmt:
        return None
    return FORMAT_REGISTRY.get(fmt.strip().lower())


__all__ = ["FORMAT_REGISTRY", "resolve_format"]
