import os
from google import genai

class AudioEngine:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.client = genai.Client(api_key=self.api_key) if self.api_key else None

    async def transcribe_audio(self, audio_bytes: bytes, mime_type: str = "audio/mp3") -> str:
        """Transcribes voice notes and audio clips into clean, indexed text."""
        if not self.client:
            return "Audio transcription subsystem offline, Sir."
        try:
            response = self.client.models.generate_content(
                model='gemini-2.0-flash',
                contents=[
                    {"mime_type": mime_type, "data": audio_bytes},
                    "Transcribe this audio recording accurately, providing a clean summary of the discussion, Sir."
                ]
            )
            return response.text.strip()
        except Exception as e:
            print(f"[Audio Engine Error]: {e}")
            return f"Audio transcription failed: {e}"
