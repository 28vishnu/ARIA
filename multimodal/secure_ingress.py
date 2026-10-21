"""Validated, bounded ingress for ARIA's existing multimodal gateway.

This is an additive adapter: it does not start providers or wire itself into the
web/Telegram entry points. Callers must opt into it where multimodal input is
accepted. Defaults are deliberately conservative and configurable.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable, Optional


class MultimodalInputError(ValueError):
    """Raised when an incoming multimodal request fails validation."""


class SecureMultimodalIngress:
    ALLOWED_MODALITIES = {"text", "image", "document", "voice", "audio", "computer"}

    def __init__(
        self,
        gateway: Any,
        *,
        max_text_chars: int = 20_000,
        max_prompt_chars: int = 2_000,
        max_image_bytes: int = 20 * 1024 * 1024,
        max_audio_bytes: int = 25 * 1024 * 1024,
        max_document_bytes: int = 40 * 1024 * 1024,
        document_roots: Optional[Iterable[str | Path]] = None,
        allow_computer_control: bool = False,
    ) -> None:
        self.gateway = gateway
        self.max_text_chars = self._positive_int(max_text_chars, "max_text_chars")
        self.max_prompt_chars = self._positive_int(max_prompt_chars, "max_prompt_chars")
        self.max_image_bytes = self._positive_int(max_image_bytes, "max_image_bytes")
        self.max_audio_bytes = self._positive_int(max_audio_bytes, "max_audio_bytes")
        self.max_document_bytes = self._positive_int(max_document_bytes, "max_document_bytes")
        configured_roots = document_roots
        if configured_roots is None:
            configured_roots = [p for p in os.getenv("ARIA_DOCUMENT_ROOTS", "").split(os.pathsep) if p]
        self.document_roots = tuple(Path(p).expanduser().resolve() for p in configured_roots)
        self.allow_computer_control = bool(allow_computer_control)

    @staticmethod
    def _positive_int(value: int, name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} must be a positive integer")
        return value

    @staticmethod
    def _bytes(payload: Any, modality: str, maximum: int) -> bytes:
        if not isinstance(payload, (bytes, bytearray, memoryview)):
            raise MultimodalInputError(f"{modality} payload must be raw bytes")
        data = bytes(payload)
        if not data:
            raise MultimodalInputError(f"{modality} payload is empty")
        if len(data) > maximum:
            raise MultimodalInputError(f"{modality} payload exceeds the {maximum}-byte limit")
        return data

    def _document_path(self, payload: Any) -> str:
        if not isinstance(payload, (str, Path)) or not str(payload).strip():
            raise MultimodalInputError("document payload must be a file path")
        path = Path(payload).expanduser().resolve(strict=True)
        if not path.is_file():
            raise MultimodalInputError("document path must refer to a regular file")
        if not self.document_roots:
            raise MultimodalInputError("document processing is disabled until ARIA_DOCUMENT_ROOTS is configured")
        if not any(path == root or root in path.parents for root in self.document_roots):
            raise MultimodalInputError("document path is outside the configured document roots")
        size = path.stat().st_size
        if size <= 0:
            raise MultimodalInputError("document file is empty")
        if size > self.max_document_bytes:
            raise MultimodalInputError(f"document exceeds the {self.max_document_bytes}-byte limit")
        return str(path)

    async def route(self, modality: str, payload: Any, *, metadata: Optional[dict] = None) -> dict:
        normalized = str(modality or "").strip().lower()
        if normalized not in self.ALLOWED_MODALITIES:
            raise MultimodalInputError("unsupported modality")
        meta = dict(metadata or {})
        prompt = meta.get("prompt")
        if prompt is not None:
            if not isinstance(prompt, str):
                raise MultimodalInputError("prompt must be text")
            if len(prompt) > self.max_prompt_chars:
                raise MultimodalInputError(f"prompt exceeds the {self.max_prompt_chars}-character limit")
        if normalized == "text":
            if not isinstance(payload, str):
                raise MultimodalInputError("text payload must be a string")
            if len(payload) > self.max_text_chars:
                raise MultimodalInputError(f"text exceeds the {self.max_text_chars}-character limit")
        elif normalized == "image":
            payload = self._bytes(payload, "image", self.max_image_bytes)
            name = meta.get("file_name", "image.jpg")
            if not isinstance(name, str) or len(name) > 255 or Path(name).name != name or name in {".", ".."}:
                raise MultimodalInputError("image file_name must be a simple filename")
            meta["file_name"] = name
        elif normalized in {"voice", "audio"}:
            payload = self._bytes(payload, "audio", self.max_audio_bytes)
        elif normalized == "document":
            payload = self._document_path(payload)
        elif normalized == "computer":
            if not self.allow_computer_control:
                return {"success": False, "capability": "computer", "blocked": True,
                        "error": "Computer control is disabled in secure multimodal ingress."}
            if not isinstance(payload, str) or not payload.strip():
                raise MultimodalInputError("computer instruction must be non-empty text")
            if len(payload) > self.max_text_chars:
                raise MultimodalInputError("computer instruction is too long")
            meta["computer_control_enabled"] = True
        result = await self.gateway.route(normalized, payload, metadata=meta)
        return result if isinstance(result, dict) else {
            "success": False, "capability": normalized, "error": "Gateway returned an invalid response"
        }
