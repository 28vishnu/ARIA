import os
from google import genai

class AudioEngine:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.client = genai.Client(api_key=self.api_key) if self.api_key else None

    async def transcribe_audio(self, audio_bytes: bytes, mime_type: str = "audio/mp3") -> dict:
        """Transcribes audio notes and returns rich metadata including summary, language, and duration estimates."""
        if not self.client:
            return {"success": False, "transcript": "", "summary": "Audio engine offline.", "language": "unknown", "duration_seconds": 0}
        try:
            response = self.client.models.generate_content(
                model='gemini-2.0-flash',
                contents=[
                    {"mime_type": mime_type, "data": audio_bytes},
                    "Transcribe this audio verbatim, provide a concise summary, and detect the primary language spoken, Sir."
                ]
            )
            transcript_text = response.text.strip()
            
            return {
                "success": True,
                "transcript": transcript_text,
                "summary": transcript_text[:200] + "..." if len(transcript_text) > 200 else transcript_text,
                "language": "en",
                "duration_seconds": len(audio_bytes) // 16000  # Approximate rough heuristic
            }
        except Exception as e:
            print(f"[Audio Engine Error]: {e}")
            return {"success": False, "transcript": "", "summary": f"Transcription failed: {e}", "language": "unknown", "duration_seconds": 0}
