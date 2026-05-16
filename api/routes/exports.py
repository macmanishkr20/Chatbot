"""
Document export endpoints: /export, /upload-template, /download/{file_name}.

Decoupled from /chat — exporting is a UI action, not a conversational intent.
"""
import logging
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from api.dependencies import _validate_user
from api.schemas import ExportRequest
from services.export.service import ExportError, run_export

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Document export — local filesystem paths ──
# Resolves to the api/ directory then up one level for repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent
GENERATED_DIR = _REPO_ROOT / "generated_docs"
TEMPLATE_DIR = _REPO_ROOT / "uploaded_templates"
GENERATED_DIR.mkdir(parents=True, exist_ok=True)
TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)

# Allowed template extensions per format family (anti-traversal + sanity check).
_ALLOWED_TEMPLATE_EXTS = {"pptx", "xlsx", "docx"}
_MAX_TEMPLATE_BYTES = 25 * 1024 * 1024  # 25 MB

_FILE_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


@router.post("/export")
async def export_document(body: ExportRequest):
    """Generate a document from a single message or the full conversation.

    PPT/Keynote require an uploaded template; Word/Excel may accept one.
    Returns a download URL the client can use to fetch the file.
    """
    _validate_user(body.user_id)
    try:
        result = await run_export(
            user_id=body.user_id,
            fmt=body.format,
            scope=body.scope,
            content=body.content,
            messages=[m.model_dump() for m in body.messages] if body.messages else None,
            template_file_id=body.template_file_id,
            title=body.title,
            preferred_language=body.preferred_language or "English",
        )
        return result
    except ExportError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("export endpoint failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Export failed")


@router.post("/upload-template")
async def upload_template(
    user_id: str = Form(...),
    template: UploadFile = File(...),
):
    """Accept a .pptx / .xlsx / .docx template upload and return a file_id.

    The returned ``template_file_id`` is passed back in the next /chat
    request so the export node can locate the template on disk and edit
    it in place when generating the document.
    """
    _validate_user(user_id)

    filename = (template.filename or "").lower()
    ext = filename.rsplit(".", 1)[-1] if "." in filename else ""
    if ext not in _ALLOWED_TEMPLATE_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported template type .{ext}. Allowed: {sorted(_ALLOWED_TEMPLATE_EXTS)}",
        )

    file_id = uuid.uuid4().hex
    dest = TEMPLATE_DIR / f"{file_id}.{ext}"

    total = 0
    try:
        with dest.open("wb") as fp:
            while True:
                chunk = await template.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > _MAX_TEMPLATE_BYTES:
                    fp.close()
                    dest.unlink(missing_ok=True)
                    raise HTTPException(status_code=413, detail="Template too large (max 25 MB)")
                fp.write(chunk)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("upload_template failed: %s", e, exc_info=True)
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="Failed to save template")

    return {
        "template_file_id": file_id,
        "extension": ext,
        "filename": template.filename,
        "size": total,
    }


@router.get("/download/{file_name}")
async def download_generated(file_name: str):
    """Serve a previously generated document for download.

    File names are issued by export_node as ``{uuid}.{ext}`` and validated
    here against an allowlist regex to prevent path traversal.
    """
    if "/" in file_name or "\\" in file_name or ".." in file_name:
        raise HTTPException(status_code=400, detail="Invalid file name")
    stem, _, ext = file_name.rpartition(".")
    if not stem or not ext or not _FILE_ID_RE.match(stem):
        raise HTTPException(status_code=400, detail="Invalid file name")

    path = GENERATED_DIR / file_name
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    media_types = {
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "txt": "text/plain",
        "json": "application/json",
    }
    return FileResponse(
        path,
        media_type=media_types.get(ext.lower(), "application/octet-stream"),
        filename=file_name,
    )
