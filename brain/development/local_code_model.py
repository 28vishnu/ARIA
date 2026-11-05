from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger("aria.development.local_code_model")


class LocalCodeModel:
    """Optional local coding-model client.

    Supports Ollama's native /api/chat endpoint and an OpenAI-compatible
    local endpoint such as llama.cpp or another local inference server.
    Credentials are never required for the local provider.
    """

    def __init__(
        self,
        *,
        backend: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.backend = (
            str(backend or os.getenv("ARIA_LOCAL_CODEGEN_BACKEND", "ollama"))
            .strip().lower()
        )
        self.base_url = (
            str(base_url or os.getenv("ARIA_LOCAL_CODEGEN_URL", "http://127.0.0.1:11434"))
            .strip().rstrip("/")
        )
        self.model = (
            str(model or os.getenv("ARIA_LOCAL_CODEGEN_MODEL", "qwen2.5-coder:7b"))
            .strip()
        )
        try:
            self.timeout = max(
                10.0,
                min(
                    600.0,
                    float(timeout or os.getenv("ARIA_LOCAL_CODEGEN_TIMEOUT", "180")),
                ),
            )
        except (TypeError, ValueError):
            self.timeout = 180.0

        if self.backend not in {"ollama", "openai_compatible"}:
            self.backend = "ollama"

    @staticmethod
    def _normalize_messages(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        for message in messages:
            if not isinstance(message, dict):
                continue
            role = str(message.get("role") or "user").strip().lower()
            if role not in {"system", "user", "assistant"}:
                role = "user"
            result.append({
                "role": role,
                "content": str(message.get("content") or ""),
            })
        return result

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.15,
        max_tokens: int = 4096,
    ) -> str:
        normalized = self._normalize_messages(messages)
        if not normalized:
            raise ValueError("Local coding-model request has no messages.")

        if self.backend == "openai_compatible":
            return await self._openai_compatible(
                normalized,
                temperature=temperature,
                max_tokens=max_tokens,
            )

        return await self._ollama(
            normalized,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    async def _ollama(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
    ) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": max(0.0, min(1.0, float(temperature))),
                "num_predict": max(1024, min(32768, int(max_tokens))),
            },
        }

        url = f"{self.base_url}/api/chat"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, json=payload)
            body = response.text[:4000]
            if response.status_code >= 400:
                raise RuntimeError(
                    f"Ollama HTTP {response.status_code}: {body}"
                )
            try:
                data = response.json()
            except Exception as exc:
                raise RuntimeError(
                    f"Ollama returned invalid JSON: {body}"
                ) from exc

        message = data.get("message") or {}
        content = message.get("content")
        if not content:
            raise RuntimeError("Ollama returned empty content.")
        return str(content).strip()

    async def _openai_compatible(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
    ) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": max(0.0, min(1.0, float(temperature))),
            "max_tokens": max(1024, min(32768, int(max_tokens))),
        }

        url = self.base_url
        if not url.endswith("/chat/completions"):
            url = f"{url}/v1/chat/completions"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                url,
                headers={"Content-Type": "application/json"},
                json=payload,
            )
            body = response.text[:4000]
            if response.status_code >= 400:
                raise RuntimeError(
                    f"Local model HTTP {response.status_code}: {body}"
                )
            try:
                data = response.json()
            except Exception as exc:
                raise RuntimeError(
                    f"Local model returned invalid JSON: {body}"
                ) from exc

        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("Local model returned no choices.")
        content = (choices[0].get("message") or {}).get("content")
        if not content:
            raise RuntimeError("Local model returned empty content.")
        return str(content).strip()

    async def health(self) -> dict[str, Any]:
        try:
            if self.backend == "ollama":
                url = f"{self.base_url}/api/tags"
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.get(url)
                healthy = response.status_code < 400
            else:
                healthy = True

            return {
                "healthy": healthy,
                "backend": self.backend,
                "base_url": self.base_url,
                "model": self.model,
            }
        except Exception as exc:
            return {
                "healthy": False,
                "backend": self.backend,
                "base_url": self.base_url,
                "model": self.model,
                "error": str(exc),
            }

    def describe(self) -> dict[str, Any]:
        return {
            "name": "local_code_model",
            "backend": self.backend,
            "model": self.model,
            "base_url": self.base_url,
            "capabilities": [
                "local_code_generation",
                "ollama",
                "openai_compatible_local_server",
            ],
            "safety": [
                "no_github_credentials",
                "no_deployment_access",
                "bounded_requests",
            ],
        }


__all__ = ["LocalCodeModel"]
