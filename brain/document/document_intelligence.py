from pathlib import Path
from typing import Optional


class DocumentIntelligence:
    """
    Handles document ingestion, extraction, summarisation and storage.
    """

    def __init__(self, memory_engine=None):
        self.memory_engine = memory_engine

    async def process_document(
        self,
        file_path: str,
        session_id: str
    ):
        """
        Full document processing pipeline.

        Phase 10:
        - Read document
        - Extract text
        - Summarise
        - Store summary
        """

        return {
            "success": False,
            "message": "Document pipeline not implemented yet."
        }

    async def extract_text(
        self,
        file_path: str
    ) -> str:
        """
        Extract text from TXT files.
        PDF and DOCX support will be added next.
        """

        suffix = Path(file_path).suffix.lower()

        if suffix == ".txt":
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()

        raise ValueError(f"Unsupported file type: {suffix}")

    async def summarize(
        self,
        text: str
    ) -> str:
        """
        Produce a concise summary.
        """

        raise NotImplementedError

    async def store(
        self,
        session_id: str,
        summary: str,
        metadata: Optional[dict] = None
    ):
        """
        Store the processed document.
        """

        raise NotImplementedError
