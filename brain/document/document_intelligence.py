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

        # Step 2: Summarise
        summary = await self.summarize(text)

        # Step 3: Store (if memory is available)
        if self.memory_engine:
            try:
                await self.store(
                    session_id=session_id,
                    summary=summary,
                    metadata={
                        "file_path": file_path
                    }
                )
            except Exception:
                pass

        return {
            "success": True,
            "text": text,
            "summary": summary
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
        metadata: Optional[dict] = None
    ):
        """
        Store the processed document.
        """

        raise NotImplementedError
