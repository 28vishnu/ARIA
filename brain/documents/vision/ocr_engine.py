from pathlib import Path
import logging

from rapidocr_onnxruntime import RapidOCR

logger = logging.getLogger("aria")


class OCREngine:

    def __init__(self):

        self.engine = RapidOCR()

        self._cache = {}

    async def extract_text(
        self,
        image_path: str,
    ) -> str:

        image_path = str(Path(image_path))

        if image_path in self._cache:
            return self._cache[image_path]

        try:

            result, _ = self.engine(image_path)

            text = "\n".join(
                line[1]
                for line in result
            ) if result else ""

            self._cache[image_path] = text

            logger.info(
                "[OCREngine] Extracted %d characters",
                len(text),
            )

            return text

        except Exception as e:

            logger.exception(
                "[OCREngine] OCR failed: %s",
                e,
            )

            return ""
