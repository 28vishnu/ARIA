import logging
import asyncio
from typing import AsyncGenerator, Optional
from multimodal.voice.stt import SpeechToTextProvider
from multimodal.voice.tts import TextToSpeechProvider

logger = logging.getLogger("aria")

class VoiceManager:
    def __init__(self, stt_provider: SpeechToTextProvider, tts_provider: TextToSpeechProvider):
        self.stt = stt_provider
        self.tts = tts_provider
        self.is_speaking = False
        self.interrupted = False
        self.listening_state = False

    async def handle_streaming_turn(self, audio_chunk_stream: AsyncGenerator[bytes, None]) -> AsyncGenerator[str, None]:
        """Manages streaming STT input and handles real-time speech interruption signals."""
        self.listening_state = True
        try:
            async for transcript_chunk in self.stt.transcribe_stream(audio_chunk_stream):
                if self.interrupted:
                    logger.info("[VoiceManager] Speech session interrupted by user.")
                    break
                yield transcript_chunk
        finally:
            self.listening_state = False
            self.interrupted = False

    async def trigger_interruption(self):
        """Signals active speech synthesis or long-running workflows to halt immediately."""
        self.interrupted = True
        self.is_speaking = False
        logger.warning("[VoiceManager] Interruption signal received ('Stop/Cancel').")
