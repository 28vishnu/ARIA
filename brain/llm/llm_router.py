import asyncio
import json
import logging
import re
from typing import Any, Dict, List

import httpx

logger = logging.getLogger("aria")


class LLMRouter:
    """
    Unified LLM interface for ARIA.

    Provider priority:
    1. Groq
    2. Gemini
    3. OpenRouter
    4. Mistral
    """

    def __init__(self, config):
        self.config = config

        self.groq_api_key = config.groq_api_key
        self.gemini_api_key = config.gemini_api_key
        self.openrouter_api_key = config.openrouter_api_key
        self.mistral_api_key = config.mistral_api_key

        self.groq_model = config.groq_model
        self.gemini_model = config.gemini_model
        self.openrouter_model = config.openrouter_model
        self.mistral_model = config.mistral_model

        self.timeout = config.timeout_seconds

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int = 1024
    ) -> str:
        """
        Generate a response using ARIA's provider failover chain.

        Provider order:
        1. Groq
        2. Gemini
        3. OpenRouter
        4. Mistral

        Temporary failures receive one short retry before ARIA
        moves automatically to the next available provider.
        """

        errors = []

        def is_temporary_error(exc: Exception) -> bool:

            if isinstance(exc, httpx.HTTPStatusError):
                return exc.response.status_code in {
                    408,
                    409,
                    425,
                    429,
                    500,
                    502,
                    503,
                    504
                }

            return isinstance(
                exc,
                (
                    httpx.TimeoutException,
                    httpx.NetworkError
                )
            )

        providers = [
            (
                "Groq",
                self.groq_api_key,
                self._groq_chat
            ),
            (
                "Gemini",
                self.gemini_api_key,
                self._gemini_chat
            ),
            (
                "OpenRouter",
                self.openrouter_api_key,
                self._openrouter_chat
            ),
            (
                "Mistral",
                self.mistral_api_key,
                self._mistral_chat
            ),
        ]

        configured_providers = 0

        for provider_name, api_key, provider_method in providers:

            if not api_key:
                continue

            configured_providers += 1

            for attempt in range(2):

                try:

                    result = await provider_method(
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens
                    )

                    logger.info(
                        "[LLMRouter] Response generated successfully "
                        "using %s.",
                        provider_name
                    )

                    return result

                except Exception as exc:

                    temporary = is_temporary_error(exc)

                    logger.warning(
                        "[LLMRouter] %s attempt %d failed: %s",
                        provider_name,
                        attempt + 1,
                        exc
                    )

                    if (
                        attempt == 0
                        and temporary
                    ):

                        logger.info(
                            "[LLMRouter] Retrying %s after "
                            "temporary failure.",
                            provider_name
                        )

                        await asyncio.sleep(1.5)

                        continue

                    errors.append(
                        f"{provider_name}: "
                        f"{type(exc).__name__}"
                    )

                    break

        if configured_providers == 0:

            raise RuntimeError(
                "No LLM provider configured."
            )

        logger.error(
            "[LLMRouter] All configured LLM providers failed: %s",
            " | ".join(errors)
        )

        raise RuntimeError(
            "All configured LLM providers failed."
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
    # OPENROUTER
    # =========================================================

    async def _openrouter_chat(
        self,
        messages: List[Dict[str, Any]],
        temperature: float,
        max_tokens: int
    ) -> str:

        url = "https://openrouter.ai/api/v1/chat/completions"

        headers = {
            "Authorization": f"Bearer {self.openrouter_api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": self.openrouter_model,
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
                "OpenRouter returned no completion choices."
            )

        content = (
            choices[0]
            .get("message", {})
            .get("content")
        )

        if not content:
            raise RuntimeError(
                "OpenRouter returned an empty response."
            )

        return str(content).strip()

    # =========================================================
    # MISTRAL
    # =========================================================

    async def _mistral_chat(
        self,
        messages: List[Dict[str, Any]],
        temperature: float,
        max_tokens: int
    ) -> str:

        url = "https://api.mistral.ai/v1/chat/completions"

        headers = {
            "Authorization": f"Bearer {self.mistral_api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": self.mistral_model,
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
                "Mistral returned no completion choices."
            )

        content = (
            choices[0]
            .get("message", {})
            .get("content")
        )

        if not content:
            raise RuntimeError(
                "Mistral returned an empty response."
            )

        return str(content).strip()

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

            logger.info(
                "[LLMRouter] Raw memory extraction response: %r",
                cleaned,
            )

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

    # =========================================================
    # LLM MEMORY RELEVANCE SELECTION
    # =========================================================

    async def select_relevant_memories(
        self,
        query: str,
        candidates: List[Dict[str, Any]]
    ) -> List[str]:
        """
        Select memory keys that are semantically relevant to a
        user's query.

        This allows ARIA to understand natural memory questions
        without requiring hard-coded aliases for every possible
        topic.
        """

        if not query or not query.strip():
            return []

        if not candidates:
            return []

        # Keep the prompt bounded if memory grows large.
        candidates = candidates[:100]

        system_prompt = """
You are ARIA's memory retrieval reasoning engine.

The user has asked a question. You are given a list of memories
ARIA has stored about that user.

Your job is ONLY to determine which stored memories are relevant
to answering the user's question.

Understand meaning, paraphrases, indirect references, and context.

For example:

Question:
Where was I thinking of going after college?

Memory:
{
  "key": "planned_postgraduate_location",
  "value": "Italy"
}

This memory is relevant even though the question does not contain
the words "postgraduate location".

Another example:

Question:
What car did I say I liked most?

Memory:
{
  "key": "favorite_car",
  "value": "Porsche"
}

This memory is relevant.

Rules:

- Select only genuinely relevant memories.
- Do not invent memory keys.
- Return keys exactly as provided.
- Do not answer the user's question.
- Do not include explanations.
- Do not use Markdown.
- If nothing is relevant, return an empty list.

Return ONLY valid JSON in this exact format:

{
  "keys": ["memory_key_1", "memory_key_2"]
}
"""

        memory_payload = []

        for candidate in candidates:

            if not isinstance(candidate, dict):
                continue

            key = str(
                candidate.get("key", "")
            ).strip()

            value = str(
                candidate.get("value", "")
            ).strip()

            if not key or not value:
                continue

            memory_payload.append({
                "key": key,
                "value": value,
                "category": str(
                    candidate.get(
                        "category",
                        "general"
                    )
                )
            })

        if not memory_payload:
            return []

        user_prompt = (
            "USER QUESTION:\n"
            f"{query}\n\n"
            "AVAILABLE MEMORIES:\n"
            f"{json.dumps(memory_payload, ensure_ascii=False)}"
        )

        messages = [
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": user_prompt
            }
        ]

        try:

            response = await self.chat(
                messages=messages,
                temperature=0.0,
                max_tokens=300
            )

            cleaned = response.strip()

            # Remove accidental Markdown fences.
            if cleaned.startswith("```"):

                cleaned = re.sub(
                    r"^```(?:json)?\s*",
                    "",
                    cleaned,
                    flags=re.IGNORECASE
                )

                cleaned = re.sub(
                    r"\s*```$",
                    "",
                    cleaned
                )

                cleaned = cleaned.strip()

            data = json.loads(cleaned)

            keys = data.get(
                "keys",
                []
            )

            if not isinstance(keys, list):
                return []

            # Prevent the LLM from inventing keys.
            valid_keys = {
                item["key"]
                for item in memory_payload
            }

            selected = []

            for key in keys:

                key = str(key).strip()

                if (
                    key
                    and key in valid_keys
                    and key not in selected
                ):
                    selected.append(key)

            logger.info(
                "[LLMRouter] Memory relevance selected %d/%d memories.",
                len(selected),
                len(memory_payload)
            )

            return selected

        except Exception as exc:

            logger.warning(
                "[LLMRouter] Memory relevance selection failed: %s",
                exc
            )

            return []
