import json
import os
from typing import Any, Dict

from google import genai
from google.genai import types


class VisionEngine:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.client = (
            genai.Client(api_key=self.api_key)
            if self.api_key
            else None
        )

    def _detect_mime_type(self, file_name: str) -> str:
        ext = file_name.split(".")[-1].lower()

        if ext == "png":
            return "image/png"

        if ext == "webp":
            return "image/webp"

        if ext == "gif":
            return "image/gif"

        if ext in ("tiff", "tif"):
            return "image/tiff"

        if ext == "bmp":
            return "image/bmp"

        return "image/jpeg"

    def _parse_json_response(self, raw_text: str) -> Dict[str, Any]:
        """
        Safely convert Gemini's response into structured vision data.
        Handles normal JSON and markdown ```json fences.
        """

        if not raw_text:
            return {
                "text": "",
                "description": "",
                "entities": [],
            }

        cleaned = raw_text.strip()

        # Remove markdown code fences if Gemini returns them.
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()

            if lines and lines[0].strip().startswith("```"):
                lines = lines[1:]

            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]

            cleaned = "\n".join(lines).strip()

        try:
            parsed = json.loads(cleaned)

            if not isinstance(parsed, dict):
                raise ValueError("Vision response is not a JSON object.")

            text = parsed.get("text", "")
            description = parsed.get("description", "")
            entities = parsed.get("entities", [])

            if not isinstance(text, str):
                text = str(text)

            if not isinstance(description, str):
                description = str(description)

            if not isinstance(entities, list):
                entities = [entities]

            return {
                "text": text.strip(),
                "description": description.strip(),
                "entities": entities,
            }

        except Exception:
            # If JSON parsing fails, preserve the complete model response
            # instead of losing useful visual information.
            return {
                "text": cleaned,
                "description": (
                    "Vision model returned an unstructured analysis."
                ),
                "entities": [],
            }

    async def analyze_visual(
        self,
        image_bytes: bytes,
        file_name: str = "image.jpg",
        prompt: str = (
            "Perform deep OCR and describe all visible text, "
            "layout, objects, people, charts, diagrams, and "
            "visual contents in detail."
        ),
    ) -> dict:
        """
        Analyze an image using Gemini multimodal vision.

        Returns:
            success:
                Whether analysis succeeded.

            text:
                Exact or best-effort OCR text.

            description:
                Detailed visual understanding.

            entities:
                Important detected entities such as names,
                dates, values, organizations, objects, etc.

            metadata:
                Information about the processed image.
        """

        if not self.client:
            return {
                "success": False,
                "text": "",
                "description": (
                    "Vision subsystem offline — "
                    "API key unconfigured."
                ),
                "entities": [],
                "metadata": {},
            }

        if not image_bytes:
            return {
                "success": False,
                "text": "",
                "description": "No image data was supplied.",
                "entities": [],
                "metadata": {},
            }

        # Maximum image size guardrail.
        if len(image_bytes) > 20 * 1024 * 1024:
            return {
                "success": False,
                "text": "",
                "description": (
                    "Image file exceeds 20MB safety limit."
                ),
                "entities": [],
                "metadata": {},
            }

        mime_type = self._detect_mime_type(file_name)

        structured_prompt = f"""
You are ARIA's visual intelligence engine.

Analyze the supplied image carefully.

User instruction:
{prompt}

Your analysis must distinguish between:
1. Text actually visible in the image.
2. Visual information inferred from the image.
3. Important entities and values.

Pay special attention to:
- Exact visible text
- Names
- Dates
- Numbers
- Organizations
- Locations
- Objects
- People
- Charts
- Tables
- Diagrams
- Screenshots
- Documents
- Signs
- Logos
- Layout and relationships between elements

Do not invent text that is not visible.

Return ONLY a valid JSON object using exactly these keys:

{{
  "text": "Exact extracted visible text, preserving useful line breaks",
  "description": "Detailed description of the image and its visual meaning",
  "entities": [
    {{
      "type": "entity type",
      "value": "entity value",
      "confidence": 0.0
    }}
  ]
}}
"""

        try:
            response = self.client.models.generate_content(
                model="gemini-2.0-flash",
                contents=[
                    types.Part.from_bytes(
                        data=image_bytes,
                        mime_type=mime_type,
                    ),
                    structured_prompt,
                ],
            )

            raw_text = (response.text or "").strip()

            parsed = self._parse_json_response(raw_text)

            return {
                "success": True,
                "text": parsed["text"],
                "description": parsed["description"],
                "entities": parsed["entities"],
                "metadata": {
                    "file_name": file_name,
                    "mime_type": mime_type,
                    "size_bytes": len(image_bytes),
                    "model": "gemini-2.0-flash",
                },
            }

        except Exception as e:
            print(f"[Vision Engine Error]: {e}")

            return {
                "success": False,
                "text": "",
                "description": f"Vision analysis failed: {e}",
                "entities": [],
                "metadata": {
                    "file_name": file_name,
                    "mime_type": mime_type,
                },
            }