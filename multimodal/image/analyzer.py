"""Image analysis adapter backed by ARIA's configured VisionEngine.

This module fails explicitly when the optional vision provider is unavailable; it
never returns a fabricated description of an image.
"""
from __future__ import annotations

import asyncio
import logging
import mimetypes
from pathlib import Path
from typing import Any

logger = logging.getLogger("aria")


class ImageAnalyzer:
    def __init__(self, llm_client: Any = None, vision_engine: Any = None) -> None:
        self.client = llm_client
        self.vision_engine = vision_engine
        if self.vision_engine is None:
            try:
                from vision_engine import VisionEngine
                self.vision_engine = VisionEngine()
            except Exception as exc:  # optional dependency/configuration
                logger.warning("[ImageAnalyzer] Vision engine unavailable: %s", exc)
                self.vision_engine = None

    @staticmethod
    def _read_payload(image_data: Any) -> tuple[bytes, str, str]:
        filename = "image.jpg"
        mime_type = "image/jpeg"
        if isinstance(image_data, (bytes, bytearray, memoryview)):
            return bytes(image_data), filename, mime_type
        if isinstance(image_data, dict):
            filename = str(image_data.get("file_name") or image_data.get("filename") or filename)
            mime_type = str(image_data.get("mime_type") or mimetypes.guess_type(filename)[0] or mime_type)
            raw = image_data.get("data", image_data.get("bytes", image_data.get("path")))
            if isinstance(raw, (bytes, bytearray, memoryview)):
                return bytes(raw), filename, mime_type
            image_data = raw
        if isinstance(image_data, (str, Path)):
            path = Path(image_data)
            data = path.read_bytes()
            filename = path.name
            mime_type = mimetypes.guess_type(filename)[0] or mime_type
            return data, filename, mime_type
        raise TypeError("Image input must be bytes, a file path, or a payload dictionary.")

    async def analyze(self, image_data: Any, prompt: str = "Describe this image.") -> str:
        """Analyze actual image bytes and return grounded model output or an error."""
        if self.vision_engine is None:
            return "Image analysis is unavailable: configure GEMINI_API_KEY and the optional google-genai dependency."
        try:
            data, filename, mime_type = await asyncio.to_thread(self._read_payload, image_data)
        except (OSError, TypeError, ValueError) as exc:
            logger.warning("[ImageAnalyzer] Invalid image input: %s", exc)
            return f"I couldn't read that image: {exc}"
        if not data:
            return "I couldn't analyze the image because the supplied file is empty."
        if len(data) > 20 * 1024 * 1024:
            return "I couldn't analyze the image because it exceeds the 20 MB limit."
        try:
            # VisionEngine's SDK call is synchronous inside its async method; run
            # that method in a worker thread so the event loop remains responsive.
            result = await asyncio.to_thread(
                lambda: asyncio.run(self.vision_engine.analyze_visual(
                    image_bytes=data,
                    file_name=filename,
                    prompt=prompt or "Describe this image.",
                ))
            )
            if not isinstance(result, dict) or not result.get("success"):
                reason = result.get("description") if isinstance(result, dict) else None
                return f"Image analysis failed: {reason or 'the vision engine returned no result.'}"
            text = str(result.get("text") or "").strip()
            description = str(result.get("description") or "").strip()
            entities = result.get("entities") or []
            parts = []
            if description:
                parts.append(description)
            if text:
                parts.append("Visible text:\n" + text)
            if entities:
                values = []
                for entity in entities:
                    if isinstance(entity, dict) and entity.get("value"):
                        values.append(f"{entity.get('type', 'entity')}: {entity['value']}")
                if values:
                    parts.append("Detected entities: " + "; ".join(values))
            return "\n\n".join(parts) or "The vision engine returned no readable description."
        except Exception:
            logger.exception("[ImageAnalyzer] Image analysis failed")
            return "Image analysis failed. Check ARIA's vision configuration and logs."
