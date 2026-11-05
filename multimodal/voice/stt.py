from abc import ABC, abstractmethod
from typing import AsyncGenerator

class SpeechToTextProvider(ABC):
    @abstractmethod
    async def transcribe(self, audio_payload: bytes) -> str:
        pass

    @abstractmethod
    async def transcribe_stream(self, audio_stream: AsyncGenerator[bytes, None]) -> AsyncGenerator[str, None]:
        pass

class TextToSpeechProvider(ABC):
    @abstractmethod
    async def synthesize(self, text: str) -> bytes:
        pass

    @abstractmethod
    async def synthesize_stream(self, text_stream: AsyncGenerator[str, None]) -> AsyncGenerator[bytes, None]:
        pass
