from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from pypdf import PdfReader


class DocumentIntelligence:
    """
    Handles document ingestion, extraction, summarisation and storage.
    """

    def __init__(
        self,
        memory_engine=None,
        llm_router=None
    ):
        self.memory_engine = memory_engine
        self.llm_router = llm_router

    async def process_document(
        self,
        file_path: str,
        session_id: str
    ):
        """
        Complete document pipeline.
        """

        # Step 1: Extract text
        text = await self.extract_text(file_path)

        # Step 2: Chunk text
        chunks = self.chunk_text(text)

        # Step 3: Summarise
        summary = await self.summarize(text)

        # Step 4: Store (if memory is available)
        if self.memory_engine:
            try:
                await self.store(
                    session_id=session_id,
                    summary=summary,
                    document_text=text,
                    metadata={
                        "file_path": file_path
                    }
                )
            except Exception:
                pass

        return {
            "success": True,
            "text": text,
            "summary": summary,
            "chunks": chunks
        }

    async def extract_text(
        self,
        file_path: str
    ) -> str:
        """
        Extract text from TXT and PDF files.
        """

        suffix = Path(file_path).suffix.lower()

        if suffix == ".txt":
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()

        if suffix == ".pdf":
            reader = PdfReader(file_path)

            pages = []

            for page in reader.pages:
                text = page.extract_text()

                if text:
                    pages.append(text)

            return "\n".join(pages)

        raise ValueError(f"Unsupported file type: {suffix}")

    def chunk_text(
        self,
        text: str,
        chunk_size: int = 1000,
        overlap: int = 200
    ):
        """
        Split text into overlapping chunks.
        """

        chunks = []

        start = 0

        while start < len(text):

            end = start + chunk_size

            chunks.append(text[start:end])

            start += chunk_size - overlap

        return chunks

    async def summarize(
        self,
        text: str
    ) -> str:
        """
        Generate an AI summary of a document.
        """

        if not self.llm_router:
            return text[:1000]

        messages = [
            {
                "role": "system",
                "content": (
                    "You are ARIA's document analyst. "
                    "Summarise the document clearly using headings, "
                    "bullet points, and key takeaways."
                )
            },
            {
                "role": "user",
                "content": text
            }
        ]

        summary = await self.llm_router.chat(messages)

        return summary

    async def store(
        self,
        session_id: str,
        summary: str,
        document_text: str,
        metadata: Optional[dict] = None
    ):
        """
        Store a processed document summary as long-term memory.
        """

        if self.memory_engine is None:
            return

        now = datetime.now(timezone.utc).isoformat()

        await self.memory_engine.memory_col.update_one(
            {
                "key": f"document_{session_id}"
            },
            {
                "$set": {
                    "key": f"document_{session_id}",
                    "value": summary,
                    "document_text": document_text,
                    "category": "document",
                    "memory_type": "document_summary",
                    "importance": "high",
                    "confidence": 1.0,
                    "metadata": metadata or {},
                    "updated_at": now
                },
                "$setOnInsert": {
                    "first_seen": now,
                    "last_used": now
                }
            },
            upsert=True
        )
