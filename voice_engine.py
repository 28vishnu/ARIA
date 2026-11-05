import os
import edge_tts

class VoiceEngine:
    def __init__(self, voice: str = "en-US-AriaNeural"):
        # Default to a professional JARVIS/assistant voice tone
        self.voice = voice

    async def text_to_speech(self, text: str, output_path: str = "aria_voice.mp3") -> str:
        """Converts assistant text responses into natural audio speech files."""
        try:
            communicate = edge_tts.Communicate(text, self.voice)
            await communicate.save(output_path)
            print(f"[Voice Engine]: Audio generated successfully at {output_path}")
            return output_path
        except Exception as e:
            print(f"[Voice Engine Error]: {e}")
            return ""
