from pathlib import Path
import logging

from PIL import Image

from ..models import Document, DocumentPage

logger = logging.getLogger("aria")


class ImageParser:
    """
    Parse image files into ARIA's document model.

    The parser keeps the original image metadata and prepares
    the document page for downstream OCR / vision processing.
    """

    async def parse(self, file_path: str) -> Document:
        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(
                f"Image file not found: {file_path}"
            )

        try:
            with Image.open(file_path) as image:
                width, height = image.size
                mode = image.mode
                format_name = image.format

        except Exception as exc:
            logger.exception(
                "[ImageParser] Failed to open image %s",
                file_path,
            )
            raise ValueError(
                f"Unable to parse image: {exc}"
            ) from exc

        document = Document(
            name=path.name,
            path=str(path),
            extension=path.suffix.lower(),
            size=path.stat().st_size,
            metadata={
                "width": width,
                "height": height,
                "mode": mode,
                "format": format_name,
                "image": True,
                "vision_pending": True,
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
                    "format": format_name,
                    "vision_pending": True,
                    "source_path": str(path),
                },
            )
        )

        logger.info(
            "[ImageParser] Parsed image %s (%dx%d, %s)",
            document.name,
            width,
            height,
            format_name,
        )

        return document