import logging
from multimodal.message import Message

logger = logging.getLogger("aria")

class MultimodalRouter:
    def __init__(self, image_analyzer=None, document_parser=None, stt_provider=None):
        self.image_analyzer = image_analyzer
        self.document_parser = document_parser
        self.stt_provider = stt_provider

    async def route(self, message: Message) -> str:
        """Dispatches incoming messages along specialized processing paths based on modality."""
        modality = message.modality

        if modality == "text":
            return str(message.content)

        elif modality == "voice" or modality == "audio":
            if self.stt_provider:
                logger.info("[MultimodalRouter] Routing audio/voice to Speech-to-Text pipeline.")
                return await self.stt_provider.transcribe(message.content)
            return str(message.content)

        elif modality == "image":
            if self.image_analyzer:
                logger.info("[MultimodalRouter] Routing image to Image Analyzer.")
                return await self.image_analyzer.analyze(message.content, message.metadata.get("prompt", ""))
            return "[Image received without analyzer]"

        elif modality == "document":
            if self.document_parser:
                logger.info("[MultimodalRouter] Routing document to Document Intelligence.")
                return await self.document_parser.parse(message.content)
            return "[Document received without parser]"

        return str(message.content)
