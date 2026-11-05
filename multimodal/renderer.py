import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("aria")

class UnifiedRenderer:
    def __init__(self, tts_provider=None):
        self.tts_provider = tts_provider

    async def render(self, response_content: Any, target_channels: list[str], metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Renders and dispatches responses across multiple output modalities (text, speech, markdown, notifications)."""
        metadata = metadata or {}
        rendered_outputs = {}

        for channel in target_channels:
            if channel == "text" or channel == "telegram" or channel == "web":
                rendered_outputs[channel] = str(response_content)
                logger.info("[Renderer] Rendered text channel for [%s]", channel)

            elif channel == "speech" and self.tts_provider:
                try:
                    audio_stream = await self.tts_provider.synthesize(str(response_content))
                    rendered_outputs["speech"] = audio_stream
                    logger.info("[Renderer] Rendered TTS audio stream.")
                except Exception as e:
                    logger.exception("[Renderer ERROR] TTS synthesis failed: %s", e)
                    rendered_outputs["speech"] = None

            elif channel == "notification":
                rendered_outputs["notification"] = {"title": metadata.get("title", "ARIA Alert"), "body": str(response_content)}
                logger.info("[Renderer] Rendered system notification.")

        return rendered_outputs
