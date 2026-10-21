"""Canonical multimodal capability gateway for ARIA.

This boundary unifies voice, vision, documents, and computer interaction
without creating a second reasoning or execution engine. Existing subsystem
implementations remain the owners of their specialized work.

The gateway is deliberately dependency-tolerant: optional providers are
loaded lazily so a missing provider cannot prevent ARIA from booting.
"""

from __future__ import annotations

import inspect
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from multimodal.secure_ingress import (
    MultimodalInputError,
    SecureMultimodalIngress,
)

logger = logging.getLogger("aria")


class _SecureGatewayDispatch:
    """Internal adapter so the secure ingress can validate before dispatch."""

    def __init__(self, owner):
        self.owner = owner

    async def route(self, modality, payload, *, metadata=None):
        return await self.owner._route_unchecked(
            modality, payload, metadata=metadata
        )


class MultimodalCapabilityGateway:
    VERSION = "ARIA-MULTIMODAL-GATEWAY-20261006"

    def __init__(
        self,
        *,
        document_pipeline=None,
        vision_engine=None,
        voice_manager=None,
        computer_tool=None,
    ) -> None:
        self.document_pipeline = document_pipeline
        self.vision_engine = vision_engine
        self.voice_manager = voice_manager
        self.computer_tool = computer_tool
        self.secure_ingress = SecureMultimodalIngress(
            _SecureGatewayDispatch(self),
            allow_computer_control=(
                str(__import__("os").getenv("ARIA_ALLOW_COMPUTER_CONTROL", "false"))
                .strip().lower() in {"1", "true", "yes", "on"}
            ),
        )

    @staticmethod
    def _availability(component: Any) -> bool:
        return component is not None

    def health(self) -> Dict[str, Any]:
        return {
            "healthy": (
                self.document_pipeline is not None
                or self.vision_engine is not None
                or self.voice_manager is not None
                or self.computer_tool is not None
            ),
            "version": self.VERSION,
            "document": self.document_pipeline is not None,
            "vision": self.vision_engine is not None,
            "voice": self.voice_manager is not None,
            "computer": self.computer_tool is not None,
            "provider_failures_are_non_fatal": True,
        }

    def capabilities(self) -> Dict[str, Dict[str, Any]]:
        return {
            "document": {
                "available": self.document_pipeline is not None,
                "read_only_by_default": True,
            },
            "vision": {
                "available": self.vision_engine is not None,
                "read_only_by_default": True,
            },
            "voice": {
                "available": self.voice_manager is not None,
                "read_only_by_default": True,
            },
            "computer": {
                "available": self.computer_tool is not None,
                "read_only_by_default": False,
                "requires_explicit_enablement": True,
            },
        }

    async def analyze_image(
        self,
        image_bytes: bytes,
        *,
        file_name: str = "image.jpg",
        prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        try:
            image_bytes = self.secure_ingress._bytes(
                image_bytes, "image", self.secure_ingress.max_image_bytes
            )
            if not isinstance(file_name, str) or len(file_name) > 255 or Path(file_name).name != file_name or file_name in {".", ".."}:
                raise MultimodalInputError("image file_name must be a simple filename")
            if prompt is not None and (not isinstance(prompt, str) or len(prompt) > self.secure_ingress.max_prompt_chars):
                raise MultimodalInputError("image prompt is invalid or too long")
        except MultimodalInputError as exc:
            return {"success": False, "capability": "vision", "error": str(exc)}

        if self.vision_engine is None:
            return {
                "success": False,
                "capability": "vision",
                "error": "Vision provider is not configured.",
            }

        method = getattr(
            self.vision_engine,
            "analyze_visual",
            None,
        )

        if method is None:
            method = getattr(
                self.vision_engine,
                "analyze",
                None,
            )

        if method is None:
            return {
                "success": False,
                "capability": "vision",
                "error": (
                    "Configured vision engine has no analysis method."
                ),
            }

        try:
            kwargs = {}

            if prompt:
                kwargs["prompt"] = prompt

            result = method(
                image_bytes,
                file_name=file_name,
                **kwargs,
            )

            if inspect.isawaitable(result):
                result = await result

            if isinstance(result, dict):
                return result

            return {
                "success": True,
                "capability": "vision",
                "result": result,
            }

        except Exception as exc:
            logger.exception(
                "[Multimodal] Vision analysis failed"
            )

            return {
                "success": False,
                "capability": "vision",
                "error": str(exc),
            }

    async def process_document(
        self,
        file_path: str,
    ) -> Dict[str, Any]:
        try:
            file_path = self.secure_ingress._document_path(file_path)
        except (MultimodalInputError, OSError, RuntimeError) as exc:
            return {"success": False, "capability": "document", "error": str(exc)}

        if self.document_pipeline is None:
            return {
                "success": False,
                "capability": "document",
                "error": (
                    "Document pipeline is not configured."
                ),
            }

        path = str(Path(file_path))

        try:
            result = self.document_pipeline.process(path)

            if inspect.isawaitable(result):
                result = await result

            return {
                "success": True,
                "capability": "document",
                "result": result,
            }

        except Exception as exc:
            logger.exception(
                "[Multimodal] Document processing failed"
            )

            return {
                "success": False,
                "capability": "document",
                "error": str(exc),
            }

    def search_documents(
        self,
        query: str,
        limit: int = 5,
    ) -> Dict[str, Any]:
        if self.document_pipeline is None:
            return {
                "success": False,
                "capability": "document",
                "error": (
                    "Document pipeline is not configured."
                ),
            }

        try:
            result = self.document_pipeline.search(
                query,
                limit=limit,
            )

            return {
                "success": True,
                "capability": "document",
                "results": result,
            }

        except Exception as exc:
            logger.exception(
                "[Multimodal] Document search failed"
            )

            return {
                "success": False,
                "capability": "document",
                "error": str(exc),
            }

    async def transcribe(
        self,
        audio_payload: bytes,
    ) -> Dict[str, Any]:
        try:
            audio_payload = self.secure_ingress._bytes(
                audio_payload, "audio", self.secure_ingress.max_audio_bytes
            )
        except MultimodalInputError as exc:
            return {"success": False, "capability": "voice", "error": str(exc)}

        if self.voice_manager is None:
            return {
                "success": False,
                "capability": "voice",
                "error": (
                    "Speech-to-text provider is not configured."
                ),
            }

        stt = getattr(
            self.voice_manager,
            "stt",
            None,
        )

        method = getattr(
            stt,
            "transcribe",
            None,
        )

        if method is None:
            return {
                "success": False,
                "capability": "voice",
                "error": (
                    "Speech-to-text provider is unavailable."
                ),
            }

        try:
            result = method(audio_payload)

            if inspect.isawaitable(result):
                result = await result

            return {
                "success": True,
                "capability": "voice",
                "text": result,
            }

        except Exception as exc:
            logger.exception(
                "[Multimodal] STT failed"
            )

            return {
                "success": False,
                "capability": "voice",
                "error": str(exc),
            }

    async def synthesize(
        self,
        text: str,
    ) -> Dict[str, Any]:
        if self.voice_manager is None:
            return {
                "success": False,
                "capability": "voice",
                "error": (
                    "Text-to-speech provider is not configured."
                ),
            }

        tts = getattr(
            self.voice_manager,
            "tts",
            None,
        )

        method = getattr(
            tts,
            "synthesize",
            None,
        )

        if method is None:
            return {
                "success": False,
                "capability": "voice",
                "error": (
                    "Text-to-speech provider is unavailable."
                ),
            }

        try:
            result = method(text)

            if inspect.isawaitable(result):
                result = await result

            return {
                "success": True,
                "capability": "voice",
                "audio": result,
            }

        except Exception as exc:
            logger.exception(
                "[Multimodal] TTS failed"
            )

            return {
                "success": False,
                "capability": "voice",
                "error": str(exc),
            }

    async def computer_action(
        self,
        query: str,
        *,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        context = dict(context or {})

        # A caller-supplied context flag is not sufficient authorization.
        # The operator must explicitly enable this capability in deployment
        # configuration as well as pass the per-request enablement flag.
        if not self.secure_ingress.allow_computer_control or not context.get(
            "computer_control_enabled",
            False,
        ):
            return {
                "success": False,
                "capability": "computer",
                "blocked": True,
                "error": (
                    "Computer control is disabled by default."
                ),
            }

        if self.computer_tool is None:
            return {
                "success": False,
                "capability": "computer",
                "error": (
                    "Computer-control tool is unavailable."
                ),
            }

        execute = getattr(
            self.computer_tool,
            "execute",
            None,
        )

        if execute is None:
            return {
                "success": False,
                "capability": "computer",
                "error": (
                    "Computer-control tool has no execute method."
                ),
            }

        try:
            result = execute(
                query,
                context,
            )

            if inspect.isawaitable(result):
                result = await result

            if isinstance(result, dict):
                return result

            return {
                "success": True,
                "capability": "computer",
                "result": result,
            }

        except Exception as exc:
            logger.exception(
                "[Multimodal] Computer action failed"
            )

            return {
                "success": False,
                "capability": "computer",
                "error": str(exc),
            }

    async def route(
        self,
        modality: str,
        payload: Any,
        *,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        try:
            return await self.secure_ingress.route(
                modality, payload, metadata=metadata
            )
        except MultimodalInputError as exc:
            normalized = str(modality or "unknown").strip().lower()
            logger.warning("[Multimodal] Rejected invalid %s input: %s", normalized, exc)
            return {
                "success": False,
                "capability": normalized,
                "blocked": True,
                "error": str(exc),
            }

    async def _route_unchecked(
        self,
        modality: str,
        payload: Any,
        *,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        metadata = dict(metadata or {})

        normalized = str(
            modality or "text"
        ).strip().lower()

        if normalized == "image":
            return await self.analyze_image(
                payload,
                file_name=str(
                    metadata.get(
                        "file_name",
                        "image.jpg",
                    )
                ),
                prompt=metadata.get("prompt"),
            )

        if normalized == "document":
            return await self.process_document(
                str(payload)
            )

        if normalized in {"voice", "audio"}:
            return await self.transcribe(
                payload
            )

        if normalized == "computer":
            return await self.computer_action(
                str(payload),
                context=metadata,
            )

        return {
            "success": True,
            "capability": "text",
            "text": str(payload),
        }
