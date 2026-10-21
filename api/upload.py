from pathlib import Path
import shutil
import tempfile
import os

from fastapi import (
    APIRouter,
    UploadFile,
    File,
    Form,
    HTTPException,
    Request,
)

router = APIRouter(tags=["Upload"])


@router.post("/upload")
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    session_id: str = Form("web"),
):
    registry = request.app.state.registry

    if not registry.has("document_intelligence"):
        raise HTTPException(
            status_code=500,
            detail="Document Intelligence is unavailable.",
        )

    document_ai = registry.get("document_intelligence")

    allowed_extensions = {
        ".pdf", ".txt", ".md", ".rst", ".log",
        ".docx", ".pptx", ".xlsx", ".xlsm", ".csv",
        ".json", ".xml", ".html", ".htm",
        ".py", ".js", ".ts", ".tsx", ".jsx", ".java",
        ".c", ".cpp", ".h", ".cs", ".go", ".rs", ".sql",
        ".yaml", ".yml", ".toml", ".ini", ".sh", ".css",
        ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif",
    }

    suffix = Path(file.filename).suffix.lower()

    if suffix not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {suffix}",
        )

    temp_path = None
    max_bytes = int(os.getenv("ARIA_MAX_UPLOAD_BYTES", str(40 * 1024 * 1024)))

    try:
        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=suffix,
        ) as temp_file:
            temp_path = temp_file.name
            total_bytes = 0
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File exceeds the {max_bytes // (1024 * 1024)} MB upload limit.",
                    )
                temp_file.write(chunk)

        result = await document_ai.process_document(
            file_path=temp_path,
            session_id=session_id,
            document_name=file.filename,
        )

        return {
            "success": True,
            "filename": file.filename,
            "summary": result.get("summary"),
        }

    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)
