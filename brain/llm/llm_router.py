import asyncio
import logging
from typing import Any, Dict, List

import httpx

logger = logging.getLogger("aria")


class LLMRouter:
    """
    Unified LLM interface for ARIA.

    Provider priority:
    1. Groq
    2. Gemini fallback
    """

    def __init__(self, config):
        self.config = config

        self.groq_api_key = config.groq_api_key
        self.gemini_api_key = config.gemini_api_key

        self.groq_model = config.groq_model
        self.gemini_model = config.gemini_model

        self.timeout = config.timeout_seconds

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int = 1024
    ) -> str:
        """
        Generate a chat response.

        Groq is attempted first.
        Gemini is used as a fallback.
        """

        errors = []

        # -----------------------------------------------------
        # Groq
        # -----------------------------------------------------

        if self.groq_api_key:
            try:
                return await self._groq_chat(
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens
                )

            except Exception as e:
                logger.exception(
                    "[LLMRouter] Groq request failed: %s",
                    e
                )

                errors.append(f"Groq: {e}")

        # -----------------------------------------------------
        # Gemini fallback
        # -----------------------------------------------------

        if self.gemini_api_key:
            try:
                return await self._gemini_chat(
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens
                )

            except Exception as e:
                logger.exception(
                    "[LLMRouter] Gemini request failed: %s",
                    e
                )

                errors.append(f"Gemini: {e}")

        if not self.groq_api_key and not self.gemini_api_key:
            raise RuntimeError(
                "No LLM provider configured. "
                "Set GROQ_API_KEY or GEMINI_API_KEY."
            )

        raise RuntimeError(
            "All configured LLM providers failed. "
            + " | ".join(errors)
        )

    # =========================================================
    # GROQ
    # =========================================================

    async def _groq_chat(
        self,
        messages: List[Dict[str, Any]],
        temperature: float,
        max_tokens: int
    ) -> str:

        url = "https://api.groq.com/openai/v1/chat/completions"

        headers = {
            "Authorization": f"Bearer {self.groq_api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": self.groq_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }

        async with httpx.AsyncClient(
            timeout=self.timeout
        ) as client:

            response = await client.post(
                url,
                headers=headers,
                json=payload
            )

            response.raise_for_status()

            data = response.json()

        choices = data.get("choices", [])

        if not choices:
            raise RuntimeError(
                "Groq returned no completion choices."
            )

        content = (
            choices[0]
            .get("message", {})
            .get("content")
        )

        if not content:
            raise RuntimeError(
                "Groq returned an empty response."
            )

        return str(content).strip()

    # =========================================================
    # GEMINI
    # =========================================================

    async def _gemini_chat(
        self,
        messages: List[Dict[str, Any]],
        temperature: float,
        max_tokens: int
    ) -> str:

        url = (
            "https://generativelanguage.googleapis.com/"
            f"v1beta/models/{self.gemini_model}:generateContent"
        )

        # Convert OpenAI-style messages to Gemini format

        system_parts = []
        contents = []

        for message in messages:

            role = message.get("role", "user")
            content = str(message.get("content", ""))

            if not content:
                continue

            if role == "system":
                system_parts.append(content)
                continue

            gemini_role = (
                "model"
                if role == "assistant"
                else "user"
            )

            contents.append({
                "role": gemini_role,
                "parts": [
                    {
                        "text": content
                    }
                ]
            })

        # Add system instructions to first user message
        if system_parts:

            system_text = "\n\n".join(system_parts)

            if contents and contents[0]["role"] == "user":

                existing = contents[0]["parts"][0]["text"]

                contents[0]["parts"][0]["text"] = (
                    system_text
                    + "\n\n"
                    + existing
                )

            else:

                contents.insert(
                    0,
                    {
                        "role": "user",
                        "parts": [
                            {
                                "text": system_text
                            }
                        ]
                    }
                )

        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens
            }
        }

        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.gemini_api_key
        }

        async with httpx.AsyncClient(
            timeout=self.timeout
        ) as client:

            response = await client.post(
                url,
                headers=headers,
                json=payload
            )

            response.raise_for_status()

            data = response.json()

        candidates = data.get("candidates", [])

        if not candidates:
            raise RuntimeError(
                "Gemini returned no candidates."
            )

        parts = (
            candidates[0]
            .get("content", {})
            .get("parts", [])
        )

        text_parts = [
            part.get("text", "")
            for part in parts
            if part.get("text")
        ]

        result = "\n".join(text_parts).strip()

        if not result:
            raise RuntimeError(
                "Gemini returned an empty response."
            )

        return result 