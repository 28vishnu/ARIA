import fitz
import logging
from pathlib import Path

from ..models import Document, DocumentPage

logger = logging.getLogger("aria")


class PDFParser:

    async def parse(self, file_path: str) -> Document:

        pdf = fitz.open(file_path)

        document = Document(
            name=Path(file_path).name,
            path=file_path,
            extension=".pdf",
            size=Path(file_path).stat().st_size,
        )

        for page_number, page in enumerate(pdf, start=1):

            text = page.get_text("text")

            document.pages.append(
                DocumentPage(
                    number=page_number,
                    text=text,
                )
            )

        pdf.close()

        logger.info(
            "[PDFParser] Parsed %d pages from %s",
            len(document.pages),
            document.name,
        )

        return document
