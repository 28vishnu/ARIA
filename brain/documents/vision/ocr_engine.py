from pathlib import Path
import logging
from typing import Dict

from rapidocr_onnxruntime import RapidOCR

logger = logging.getLogger("aria")


class OCREngine:
    """
    Local OCR engine for document images.

    Vision/Gemini handles deep visual understanding.
    RapidOCR provides a fast dedicated OCR layer for
    document text extraction.
    """

    def __init__(self):
        self.engine = RapidOCR()
        self._cache: Dict[str, str] = {}

    async def extract_text(
        self,
        image_path: str,
    ) -> str:
        """
        Extract text from an image using RapidOCR.

        Results are cached by resolved image path so repeated
        analysis of the same document page does not unnecessarily
        execute OCR again.
        """

        path = Path(image_path)

        if not path.exists():
            logger.warning(
                "[OCREngine] Image not found: %s",
                image_path,
            )
            return ""

        try:
            cache_key = str(path.resolve())
        except Exception:
            cache_key = str(path)

        if cache_key in self._cache:
            logger.debug(
                "[OCREngine] Returning cached OCR result: %s",
                cache_key,
            )
            return self._cache[cache_key]

        try:
            result, _ = self.engine(cache_key)

            if not result:
                self._cache[cache_key] = ""
                return ""

            text_parts = []

            for line in result:
                if not line or len(line) < 2:
                    continue

                text = str(line[1]).strip()

                if text:
                    text_parts.append(text)

            text = "\n".join(text_parts).strip()

            self._cache[cache_key] = text

            logger.info(
                "[OCREngine] Extracted %d characters from %s",
                len(text),
                cache_key,
            )

            return text

        except Exception as e:
            logger.exception(
                "[OCREngine] OCR failed for %s: %s",
                cache_key,
                e,
            )

            return ""

    def clear_cache(self) -> None:
        """Clear all cached OCR results."""
        self._cache.clear()
        logger.debug("[OCREngine] OCR cache cleared.")