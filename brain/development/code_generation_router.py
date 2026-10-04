"""
ARIA Phase 1 — Dedicated Code Generation Router.

A provider-isolated router used ONLY by ARIA's self-development pipeline.
It deliberately does not reuse the general LLMRouter so large development
requests cannot enter the normal multi-provider reasoning/fallback chain.

Supported providers:
    groq, mistral, openrouter, gemini

The provider is selected by ARIA_CODEGEN_PROVIDER (default: groq).
Fallback is disabled by default and can be explicitly enabled with
ARIA_CODEGEN_ALLOW_FALLBACK=true.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger("aria.development.codegen_router")


class CodeGenerationRouter:
    """Dedicated, bounded provider router for code generation."""

    DEFAULT_PROVIDER = "groq"
    DEFAULT_TIMEOUT = 90.0
    DEFAULT_MAX_TOKENS = 4096
    DEFAULT_TEMPERATURE = 0.15
    DEFAULT_MAX_INPUT_CHARS = 60_000

    def __init__(
        self,
        config: Any | None = None,
        *,
        provider: str | None = None,
        timeout: float | None = None,
        max_input_chars: int | None = None,
        allow_fallback: bool | None = None,
    ) -> None:
        self.config = config
        self.provider = self._normalize_provider(
            provider or os.getenv("ARIA_CODEGEN_PROVIDER", self.DEFAULT_PROVIDER)
        )
        self.timeout = self._number(
            timeout,
            os.getenv("ARIA_CODEGEN_TIMEOUT", str(self.DEFAULT_TIMEOUT)),
            self.DEFAULT_TIMEOUT,
            minimum=10.0,
            maximum=300.0,
        )
        self.max_input_chars = int(
            self._number(
                max_input_chars,
                os.getenv("ARIA_CODEGEN_MAX_INPUT_CHARS", str(self.DEFAULT_MAX_INPUT_CHARS)),
                self.DEFAULT_MAX_INPUT_CHARS,
                minimum=4_000,
                maximum=120_000,
            )
        )
        self.allow_fallback = self._bool(
            allow_fallback,
            os.getenv("ARIA_CODEGEN_ALLOW_FALLBACK", "false"),
        )

        self._providers = self._build_provider_order()

        logger.info(
            "[Phase1][CodeGenerationRouter] Initialized | provider=%s | fallback=%s | max_input_chars=%s",
            self.provider,
            self.allow_fallback,
            self.max_input_chars,
        )

    @staticmethod
    def _normalize_provider(value: str) -> str:
        normalized = str(value or "").strip().lower().replace("-", "_")
        aliases = {
            "open_router": "openrouter",
            "google": "gemini",
        }
        normalized = aliases.get(normalized, normalized)
        if normalized not in {"groq", "mistral", "openrouter", "gemini"}:
            return CodeGenerationRouter.DEFAULT_PROVIDER
        return normalized

    @staticmethod
    def _number(
        value: Any,
        fallback: Any,
        default: float,
        *,
        minimum: float,
        maximum: float,
    ) -> float:
        candidate = value if value is not None else fallback
        try:
            parsed = float(candidate)
        except (TypeError, ValueError):
            parsed = default
        return max(minimum, min(maximum, parsed))

    @staticmethod
    def _bool(value: Any, fallback: str) -> bool:
        if value is None:
            value = fallback
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    def _get(self, name: str, default: str = "") -> str:
        env = os.getenv(name)
        if env is not None:
            return env.strip()
        if self.config is not None:
            value = getattr(self.config, name.lower(), None)
            if value is not None:
                return str(value).strip()
        return default

    def _model(self, provider: str) -> str:
        defaults = {
            "groq": "llama-3.3-70b-versatile",
            "mistral": "mistral-small-latest",
            "openrouter": "openai/gpt-oss-20b:free",
            "gemini": "gemini-2.0-flash",
        }
        env_names = {
            "groq": "GROQ_MODEL",
            "mistral": "MISTRAL_MODEL",
            "openrouter": "OPENROUTER_MODEL",
            "gemini": "GEMINI_MODEL",
        }
        return self._get(env_names[provider], defaults[provider])

    def _api_key(self, provider: str) -> str:
        names = {
            "groq": "GROQ_API_KEY",
            "mistral": "MISTRAL_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
            "gemini": "GEMINI_API_KEY",
        }
        return self._get(names[provider])

    def _build_provider_order(self) -> list[str]:
        if not self.allow_fallback:
            return [self.provider]
        preferred = [self.provider, "groq", "mistral", "gemini", "openrouter"]
        result: list[str] = []
        for item in preferred:
            if item not in result:
                result.append(item)
        return result

    @staticmethod
    def _normalize_messages(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        for message in messages:
            if not isinstance(message, dict):
                continue
            role = str(message.get("role") or "user").strip().lower()
            content = str(message.get("content") or "")
            if role not in {"system", "user", "assistant"}:
                role = "user"
            result.append({"role": role, "content": content})
        return result

    def _bounded_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, str]]:
        normalized = self._normalize_messages(messages)
        total = sum(len(item["content"]) for item in normalized)
        if total <= self.max_input_chars:
            return normalized

        remaining = self.max_input_chars
        bounded: list[dict[str, str]] = []
        for item in normalized:
            if remaining <= 0:
                break
            content = item["content"]
            if len(content) > remaining:
                content = content[:remaining]
            bounded.append({"role": item["role"], "content": content})
            remaining -= len(content)
        return bounded

    @staticmethod
    def _extract_openai_content(data: dict[str, Any]) -> str:
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError(f"Provider returned no choices: {data}")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if content is None:
            raise RuntimeError(f"Provider returned empty content: {data}")
        return str(content).strip()

    async def _chat_openai_compatible(
        self,
        provider: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> str:
        key = self._api_key(provider)
        if not key:
            raise RuntimeError(f"{provider} API key is not configured")

        urls = {
            "groq": "https://api.groq.com/openai/v1/chat/completions",
            "mistral": "https://api.mistral.ai/v1/chat/completions",
            "openrouter": "https://openrouter.ai/api/v1/chat/completions",
        }
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        if provider == "openrouter":
            headers["HTTP-Referer"] = os.getenv("ARIA_CODEGEN_REFERER", "https://aria.local")
            headers["X-Title"] = "ARIA Code Generation"

        payload = {
            "model": self._model(provider),
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(urls[provider], headers=headers, json=payload)
            text = response.text[:4000]
            if response.status_code >= 400:
                raise RuntimeError(f"{provider} HTTP {response.status_code}: {text}")
            try:
                data = response.json()
            except Exception as exc:
                raise RuntimeError(f"{provider} returned invalid JSON: {text}") from exc
            return self._extract_openai_content(data)

    async def _chat_gemini(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> str:
        key = self._api_key("gemini")
        if not key:
            raise RuntimeError("gemini API key is not configured")

        try:
            from google import genai
        except ImportError as exc:
            raise RuntimeError("google-genai package is not installed") from exc

        prompt = "\n\n".join(
            f"{item['role'].upper()}: {item['content']}"
            for item in messages
        )
        client = genai.Client(api_key=key)

        def _call() -> str:
            result = client.models.generate_content(
                model=self._model("gemini"),
                contents=prompt,
                config={
                    "temperature": temperature,
                    "max_output_tokens": max_tokens,
                },
            )
            content = getattr(result, "text", None)
            if not content:
                raise RuntimeError("Gemini returned empty content")
            return str(content).strip()

        return await asyncio.to_thread(_call)

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        task: str = "coding",
        context: dict[str, Any] | None = None,
    ) -> str:
        """Generate code using only the dedicated coding provider route."""
        bounded = self._bounded_messages(messages)
        temperature = max(0.0, min(1.0, float(temperature)))
        max_tokens = max(1024, min(8192, int(max_tokens)))

        logger.info(
            "[Phase1][CodeGenerationRouter] coding request | provider=%s | model=%s | input_chars=%d | max_tokens=%d | task=%s",
            self.provider,
            self._model(self.provider),
            sum(len(item["content"]) for item in bounded),
            max_tokens,
            task,
        )

        errors: list[str] = []
        for provider in self._providers:
            try:
                if provider == "gemini":
                    result = await self._chat_gemini(bounded, temperature, max_tokens)
                else:
                    result = await self._chat_openai_compatible(
                        provider,
                        bounded,
                        temperature,
                        max_tokens,
                    )
                if not result:
                    raise RuntimeError("provider returned an empty response")
                logger.info(
                    "[Phase1][CodeGenerationRouter] success | provider=%s | chars=%d",
                    provider,
                    len(result),
                )
                return result
            except Exception as exc:
                message = f"{provider}: {exc}"
                errors.append(message)
                logger.warning("[Phase1][CodeGenerationRouter] %s", message)
                if not self.allow_fallback:
                    break

        raise RuntimeError(
            "Dedicated code-generation provider failed: " + "; ".join(errors)
        )


__all__ = ["CodeGenerationRouter"]
