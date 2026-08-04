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
        ".pdf",
        ".txt",
        ".docx",
        ".pptx",
        ".png",
        ".jpg",
        ".jpeg",
        ".zip",
    }

    suffix = Path(file.filename).suffix.lower()

    if suffix not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {suffix}",
        )

    temp_path = None

    try:
        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=suffix,
        ) as temp_file:

            shutil.copyfileobj(file.file, temp_file)
            temp_path = temp_file.name

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
