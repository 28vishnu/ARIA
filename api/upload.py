from pathlib import Path
import shutil
import tempfile

from fastapi import APIRouter, UploadFile, File, Form, HTTPException

from core.bootstrap import registry

router = APIRouter(tags=["Upload"])


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    session_id: str = Form("web")
):
    document_ai = registry.get("document_intelligence")

    suffix = Path(file.filename).suffix.lower()

    with tempfile.NamedTemporaryFile(
        delete=False,
        suffix=suffix
    ) as temp_file:

        shutil.copyfileobj(file.file, temp_file)

        temp_path = temp_file.name

    result = await document_ai.process_document(
        file_path=temp_path,
        session_id=session_id,
        document_name=file.filename
    )

    return {
        "success": True,
        "filename": file.filename,
        "summary": result["summary"]
    }
