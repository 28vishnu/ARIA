import asyncio
import json
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

    # =========================================================
    # GEMINI EMBEDDINGS
    # =========================================================

    async def embed(
        self,
        texts: List[str],
        task_type: str = "RETRIEVAL_DOCUMENT"
    ) -> List[List[float]]:
        """
        Generate embeddings remotely using Gemini.

        This replaces the local SentenceTransformer model,
        avoiding PyTorch/Transformers RAM usage on Render.

        task_type:
            RETRIEVAL_DOCUMENT -> when indexing document chunks
            RETRIEVAL_QUERY    -> when embedding a user's search/question
        """

        if not self.gemini_api_key:
            raise RuntimeError(
                "Gemini API key is required for embeddings."
            )

        if not texts:
            return []

        model = "gemini-embedding-001"

        url = (
            "https://generativelanguage.googleapis.com/"
            f"v1beta/models/{model}:batchEmbedContents"
        )

        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.gemini_api_key
        }

        requests = []

        for text in texts:
            cleaned_text = str(text).strip()

            if not cleaned_text:
                cleaned_text = " "

            requests.append({
                "model": f"models/{model}",
                "content": {
                    "parts": [
                        {
                            "text": cleaned_text
                        }
                    ]
                },
                "taskType": task_type
            })

        payload = {
            "requests": requests
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

        embedding_objects = data.get(
            "embeddings",
            []
        )

        if len(embedding_objects) != len(texts):
            raise RuntimeError(
                "Gemini returned an unexpected number of embeddings."
            )

        embeddings = []

        for embedding in embedding_objects:

            values = embedding.get(
                "values",
                []
            )

            if not values:
                raise RuntimeError(
                    "Gemini returned an empty embedding."
                )

            embeddings.append(values)

        logger.info(
            "[LLMRouter] Gemini generated %d embeddings.",
            len(embeddings)
        )

        return embeddings

    # =========================================================
    # LLM MEMORY EXTRACTION
    # =========================================================

    async def extract_memories(
        self,
        user_text: str
    ) -> List[Dict[str, Any]]:
        """
        Understand natural-language user statements and extract
        zero or more long-term memories.

        This uses the existing LLM provider instead of requiring
        hundreds of hard-coded regex patterns.
        """

        if not user_text or not user_text.strip():
            return []

        system_prompt = """
You are ARIA's memory understanding engine.

Your job is to identify useful long-term information that the
user explicitly tells ARIA about themselves, their preferences,
goals, education, projects, plans, relationships with things,
or interaction preferences.

Extract MULTIPLE memories when one message contains multiple facts.

Do NOT store:
- ordinary questions
- greetings
- temporary conversation
- general knowledge
- passwords
- API keys
- authentication tokens
- Aadhaar numbers
- PAN numbers
- banking information
- OTPs
- highly sensitive private credentials

Return ONLY valid JSON.

Required format:

{
  "memories": [
    {
      "key": "short_stable_key",
      "value": "memory value",
      "category": "category",
      "memory_type": "fact_or_preference",
      "importance": "low_medium_or_high"
    }
  ]
}

Examples:

User:
My name is John and I study computer science.

Output:
{
  "memories": [
    {
      "key": "name",
      "value": "John",
      "category": "identity",
      "memory_type": "fact",
      "importance": "high"
    },
    {
      "key": "field_of_study",
      "value": "computer science",
      "category": "education",
      "memory_type": "fact",
      "importance": "medium"
    }
  ]
}

User:
My favourite car is Porsche but I prefer dark mode.

Output:
{
  "memories": [
    {
      "key": "favorite_car",
      "value": "Porsche",
      "category": "preference",
      "memory_type": "preference",
      "importance": "medium"
    },
    {
      "key": "interface_preference",
      "value": "dark mode",
      "category": "interaction_preference",
      "memory_type": "preference",
      "importance": "medium"
    }
  ]
}

If there is nothing worth remembering return:

{
  "memories": []
}
"""

        messages = [
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": user_text
            }
        ]

        try:
            response = await self.chat(
                messages=messages,
                temperature=0.1,
                max_tokens=700
            )

            # Remove accidental Markdown code fences.
            cleaned = response.strip()

            if cleaned.startswith("```"):
                cleaned = cleaned.replace("```json", "", 1)
                cleaned = cleaned.replace("```", "")
                cleaned = cleaned.strip()

            data = json.loads(cleaned)

            memories = data.get("memories", [])

            if not isinstance(memories, list):
                return []

            valid_memories = []

            for memory in memories:

                if not isinstance(memory, dict):
                    continue

                key = str(memory.get("key", "")).strip()
                value = str(memory.get("value", "")).strip()

                if not key or not value:
                    continue

                valid_memories.append({
                    "key": key.lower().replace(" ", "_"),
                    "value": value,
                    "category": str(
                        memory.get("category", "general")
                    ),
                    "memory_type": str(
                        memory.get("memory_type", "fact")
                    ),
                    "importance": str(
                        memory.get("importance", "medium")
                    )
                })

            logger.info(
                "[LLMRouter] Memory interpreter extracted %d memories.",
                len(valid_memories)
            )

            return valid_memories

        except Exception as exc:

            logger.warning(
                "[LLMRouter] Memory extraction failed: %s",
                exc
            )

            return []
