"""Optional Gemini-backed audio transcription for ARIA.

The application can start when the optional ``google-genai`` package is not
installed. Audio transcription remains unavailable until the dependency and
GEMINI_API_KEY are configured.
"""

from __future__ import annotations

import os
import logging
import asyncio
from typing import Any

logger = logging.getLogger(__name__)

try:
    from google import genai as _genai
except (ImportError, AttributeError) as exc:  # optional dependency
    _genai = None
    _GENAI_IMPORT_ERROR: Exception | None = exc
else:
    _GENAI_IMPORT_ERROR = None


class AudioEngine:
    """Transcribe audio using Gemini when the SDK and API key are available."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.client: Any | None = None
        self.unavailable_reason: str | None = None

        if _genai is None:
            self.unavailable_reason = (
                "The optional google-genai package is not available. "
                "Install the project's requirements to enable audio transcription."
            )
        elif not self.api_key:
            self.unavailable_reason = "GEMINI_API_KEY is not configured."
        else:
            try:
                self.client = _genai.Client(api_key=self.api_key)
            except Exception as exc:
                logger.warning("Could not initialize Gemini audio client: %s", exc)
                self.unavailable_reason = "The Gemini audio client could not be initialized."

    async def transcribe_audio(
        self,
        audio_bytes: bytes,
        mime_type: str = "audio/mp3",
    ) -> dict[str, Any]:
        """Transcribe an audio byte string, returning a stable result schema."""
        if not audio_bytes:
            return {
                "success": False,
                "transcript": "",
                "summary": "No audio data was provided.",
                "language": "unknown",
                "duration_seconds": 0,
            }

        if self.client is None:
            return {
                "success": False,
                "transcript": "",
                "summary": self.unavailable_reason or "Audio engine offline.",
                "language": "unknown",
                "duration_seconds": 0,
            }

        try:
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model="gemini-2.0-flash",
                contents=[
                    {"mime_type": mime_type, "data": audio_bytes},
                    (
                        "Transcribe this audio verbatim. Return the transcript first, "
                        "then a concise summary and the primary language if identifiable. "
                        "Do not invent speech that is not audible."
                    ),
                ],
            )
            transcript = (getattr(response, "text", None) or "").strip()
            if not transcript:
                return {
                    "success": False,
                    "transcript": "",
                    "summary": "The transcription service returned no text.",
                    "language": "unknown",
                    "duration_seconds": 0,
                }
            return {
                "success": True,
                "transcript": transcript,
                "summary": transcript[:200] + ("..." if len(transcript) > 200 else ""),
                "language": "unknown",
                "duration_seconds": 0,
            }
        except Exception:
            logger.exception("Audio transcription failed")
            return {
                "success": False,
                "transcript": "",
                "summary": "Transcription failed. Check ARIA's audio configuration and logs.",
                "language": "unknown",
                "duration_seconds": 0,
            }
