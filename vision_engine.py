import os
from google import genai
from google.genai import types

class VisionEngine:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.client = genai.Client(api_key=self.api_key) if self.api_key else None

    def _detect_mime_type(self, file_name: str) -> str:
        ext = file_name.split(".")[-1].lower()
        if ext in ["png"]: return "image/png"
        if ext in ["webp"]: return "image/webp"
        if ext in ["gif"]: return "image/gif"
        if ext in ["tiff", "tif"]: return "image/tiff"
        return "image/jpeg"

    async def analyze_visual(self, image_bytes: bytes, file_name: str = "image.jpg", prompt: str = "Perform deep OCR and describe all visible text, layout, and visual contents in detail.") -> dict:
        """Analyzes images dynamically with MIME detection, size validation, and structured output."""
        if not self.client:
            return {"success": False, "text": "", "description": "Vision subsystem offline — API key unconfigured.", "entities": [], "metadata": {}}
        
        # File size validation (Max 20MB guardrail)
        if len(image_bytes) > 20 * 1024 * 1024:
            return {"success": False, "text": "", "description": "Image file exceeds 20MB safety limit.", "entities": [], "metadata": {}}

        mime_type = self._detect_mime_type(file_name)

        structured_prompt = f"""
{prompt}
Return your analysis as a structured JSON object with keys:
- "text": Exact extracted OCR text
- "description": Comprehensive scene/chart summary
- "entities": List of key entities discovered (names, dates, values, organizations)
"""
        try:
            response = self.client.models.generate_content(
                model='gemini-2.0-flash',
                contents=[
                    types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                    structured_prompt
                ]
            )
            raw_text = response.text.strip()
            
            return {
                "success": True,
                "text": raw_text,
                "description": "Multimodal visual inspection and OCR complete.",
                "entities": [],
                "metadata": {"file_name": file_name, "mime_type": mime_type, "size_bytes": len(image_bytes)}
            }
        except Exception as e:
            print(f"[Vision Engine Error]: {e}")
            return {"success": False, "text": "", "description": f"Vision analysis failed: {e}", "entities": [], "metadata": {}}
