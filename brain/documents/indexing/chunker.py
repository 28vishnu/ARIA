import logging
from typing import List

from ..models import DocumentChunk

logger = logging.getLogger("aria")


class Chunker:

    def __init__(
        self,
        chunk_size: int = 1200,
        overlap: int = 200,
    ):
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk_document(self, document):

        chunks = []

        for page in document.pages:

            page_chunks = self.chunk_text(
                page.text,
                page.number,
                document.id,
            )

            chunks.extend(page_chunks)

        logger.info(
            "[Chunker] Created %d chunks",
            len(chunks),
        )

        return chunks

    def chunk_text(
        self,
        text: str,
        page: int,
        document_id: str,
    ) -> List[DocumentChunk]:

        if not text.strip():
            return []

        chunks = []

        start = 0

        while start < len(text):

            end = min(
                start + self.chunk_size,
                len(text),
            )

            chunk = text[start:end]

            chunks.append(
                DocumentChunk(
                    document_id=document_id,
                    page=page,
                    text=chunk,
                )
            )

            if end == len(text):
                break

            start = end - self.overlap

        return chunks
