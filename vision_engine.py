import os
from google import genai
from google.genai import types

class VisionEngine:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.client = genai.Client(api_key=self.api_key) if self.api_key else None

    async def analyze_image(self, image_bytes: bytes, prompt: str = "Describe this image in detail, extracting any visible text or data.") -> str:
        """Analyzes images, certificates, or screenshots using Gemini's multimodal vision model."""
        if not self.client:
            return "Vision subsystem offline — Gemini API key not configured."
        try:
            response = self.client.models.generate_content(
                model='gemini-2.0-flash',
                contents=[
                    types.Part.from_bytes(
                        data=image_bytes,
                        mime_type='image/jpeg',
                    ),
                    prompt
                ]
            )
            return response.text.strip()
        except Exception as e:
            print(f"[Vision Engine Error]: {e}")
            return f"Failed to process visual data: {e}"
