from pathlib import Path
import logging

from PIL import Image

from ..models import Document, DocumentPage

logger = logging.getLogger("aria")


class ImageParser:

    async def parse(self, file_path: str) -> Document:

        image = Image.open(file_path)

        width, height = image.size

        document = Document(
            name=Path(file_path).name,
            path=file_path,
            extension=Path(file_path).suffix.lower(),
            size=Path(file_path).stat().st_size,
            metadata={
                "width": width,
                "height": height,
                "mode": image.mode,
            },
        )

        document.pages.append(
            DocumentPage(
                number=1,
                text="",
                metadata={
                    "image": True,
                    "width": width,
                    "height": height,
                },
            )
        )

        image.close()

        logger.info(
            "[ImageParser] Parsed image %s (%dx%d)",
            document.name,
            width,
            height,
        )

        return document
