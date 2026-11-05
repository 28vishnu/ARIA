import json
import logging
import re
import time
from typing import Any, Dict, Optional

from brain.models.intent import Intent

logger = logging.getLogger("aria")


class IntentAnalyzer:
    """
    ARIA's Phase-1 intent understanding layer.

    Responsibilities:
    - Normalize user requests
    - Detect conversational intent
    - Detect required capabilities
    - Preserve explicit entities
    - Use LLM semantic classification when available
    - Fall back safely to deterministic local classification
    - Never execute tools or answer the user
    """

    GREETINGS = {
        "hi",
        "hello",
        "hey",
        "greetings",
        "good morning",
        "good evening",
        "good afternoon",
    }

    MEMORY_TRIGGERS = {
        "remember",
        "recall",
        "forget",
        "memory",
        "did i",
        "told you",
        "you remember",
        "what did i tell you",
        "what do you know about me",
    }

    DOCUMENT_TRIGGERS = {
        "pdf",
        "file",
        "document",
        "resume",
        "attachment",
        "uploaded",
        "upload",
    }

    DOCUMENT_ACTIONS = {
        "summarize",
        "summary",
        "analyze",
        "analyse",
        "review",
        "read",
        "extract",
        "parse",
        "explain this file",
    }

    SEARCH_TRIGGERS = {
        "search",
        "find",
        "look up",
        "lookup",
        "locate",
        "search for",
        "look for",
    }

    WEB_TRIGGERS = {
        "latest",
        "today",
        "current",
        "recent",
        "news",
        "this week",
        "this month",
        "price",
        "weather",
        "live",
        "now",
        "what is happening",
    }

    PLANNING_TRIGGERS = {
        "plan",
        "planning",
        "roadmap",
        "strategy",
        "steps",
        "how do i build",
        "how should i build",
        "how can i build",
        "design",
        "architecture",
        "workflow",
    }

    CODING_TRIGGERS = {
        "code",
        "coding",
        "python",
        "java",
        "javascript",
        "typescript",
        "program",
        "programming",
        "function",
        "class",
        "api",
        "bug",
        "debug",
        "debugging",
        "error",
        "exception",
        "syntax",
        "implement",
        "refactor",
        "repository",
        "github",
    }

    TOOL_TRIGGERS = {
        "run",
        "execute",
        "open",
        "send",
        "create",
        "delete",
        "download",
        "upload",
        "install",
        "search",
        "calculate",
        "convert",
    }

    FOLLOW_UP_TRIGGERS = {
        "continue",
        "go on",
        "tell me more",
        "explain more",
        "more",
        "what about",
        "how about",
        "which one",
        "which is better",
        "why",
        "then",
        "and then",
        "next",
    }

    def __init__(self, llm_router=None):
        self.llm_router = llm_router
        self.intent_history = []

    # =========================================================
    # NORMALIZATION
    # =========================================================

    def normalize(self, query: str) -> str:
        """
        Normalize user text without destroying the original request.
        """

        cleaned = str(query or "").strip().lower()

        cleaned = re.sub(
            r"\s+",
            " ",
            cleaned,
        )

        return cleaned

    # Backwards-compatible alias.
    def _normalize(self, query: str) -> str:
        return self.normalize(query)

    # =========================================================
    # ENTITY EXTRACTION
    # =========================================================

    def _extract_entities(
        self,
        query: str,
    ) -> list:
        """
        Extract lightweight explicit entities.

        This is intentionally conservative. The knowledge graph
        and semantic reasoning layers perform deeper entity analysis.
        """

        entities = []

        text = str(query or "").strip()

        # Explicit comparison entities.
        comparison_patterns = [
            r"\bbetween\s+(.+?)\s+and\s+(.+?)(?:[?.!,]|$)",
            r"\bcompare\s+(.+?)\s+(?:and|vs\.?|versus)\s+(.+?)(?:[?.!,]|$)",
            r"\b(.+?)\s+(?:vs\.?|versus)\s+(.+?)(?:[?.!,]|$)",
        ]

        for pattern in comparison_patterns:
            match = re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            )

            if not match:
                continue

            for value in match.groups():
                value = re.sub(
                    r"\s+",
                    " ",
                    value,
                ).strip(" .,!?:;")

                if value and len(value) <= 100:
                    entities.append(value)

            break

        return list(
            dict.fromkeys(entities)
        )

    # =========================================================
    # INTENT HISTORY
    # =========================================================

    def _remember_intent(
        self,
        intent: Intent,
    ) -> Intent:
        self.intent_history.append(intent)

        if len(self.intent_history) > 100:
            self.intent_history.pop(0)

        return intent

    # =========================================================
    # LOCAL CLASSIFICATION
    # =========================================================

    def _local_intent(
        self,
        original_query: str,
        query: str,
    ) -> Intent:

        entities = self._extract_entities(
            original_query
        )

        # -----------------------------------------------------
        # EMPTY
        # -----------------------------------------------------

        if not query:
            return Intent(
                original_query=original_query,
                normalized_query=query,
                intent_type="conversation",
                confidence=0.50,
                entities=entities,
                requires_memory=True,
                requires_documents=False,
                requires_web=False,
                requires_reasoning=False,
                metadata={
                    "source": "local",
                },
                timestamp=time.time(),
            )

        # -----------------------------------------------------
        # GREETING
        # -----------------------------------------------------

        if (
            query in self.GREETINGS
            or any(
                query.startswith(
                    greeting + " "
                )
                for greeting in self.GREETINGS
            )
        ):
            return Intent(
                original_query=original_query,
                normalized_query=query,
                intent_type="greeting",
                confidence=0.99,
                entities=entities,
                requires_memory=False,
                requires_documents=False,
                requires_web=False,
                requires_reasoning=False,
                metadata={
                    "source": "local",
                },
                timestamp=time.time(),
            )

        # -----------------------------------------------------
        # FOLLOW-UP
        # -----------------------------------------------------

        if (
            query in self.FOLLOW_UP_TRIGGERS
            or any(
                query.startswith(
                    trigger + " "
                )
                for trigger in self.FOLLOW_UP_TRIGGERS
            )
        ):
            return Intent(
                original_query=original_query,
                normalized_query=query,
                intent_type="follow_up",
                confidence=0.94,
                entities=entities,
                requires_memory=True,
                requires_documents=False,
                requires_web=False,
                requires_reasoning=True,
                metadata={
                    "source": "local",
                    "follow_up": True,
                },
                timestamp=time.time(),
            )

        # -----------------------------------------------------
        # MEMORY
        # -----------------------------------------------------

        if any(
            trigger in query
            for trigger in self.MEMORY_TRIGGERS
        ):
            return Intent(
                original_query=original_query,
                normalized_query=query,
                intent_type="memory",
                confidence=0.95,
                entities=entities,
                requires_memory=True,
                requires_documents=False,
                requires_web=False,
                requires_reasoning=True,
                metadata={
                    "source": "local",
                },
                timestamp=time.time(),
            )

        # -----------------------------------------------------
        # DOCUMENT
        # -----------------------------------------------------

        has_document = any(
            trigger in query
            for trigger in self.DOCUMENT_TRIGGERS
        )

        has_document_action = any(
            action in query
            for action in self.DOCUMENT_ACTIONS
        )

        if has_document and (
            has_document_action
            or "file" in query
            or "document" in query
            or "pdf" in query
        ):
            return Intent(
                original_query=original_query,
                normalized_query=query,
                intent_type="document",
                confidence=0.96,
                entities=entities,
                requires_memory=False,
                requires_documents=True,
                requires_web=False,
                requires_reasoning=True,
                metadata={
                    "source": "local",
                },
                timestamp=time.time(),
            )

        # -----------------------------------------------------
        # CODING
        # -----------------------------------------------------

        if any(
            trigger in query
            for trigger in self.CODING_TRIGGERS
        ):
            return Intent(
                original_query=original_query,
                normalized_query=query,
                intent_type="coding",
                confidence=0.92,
                entities=entities,
                requires_memory=True,
                requires_documents=False,
                requires_web=False,
                requires_reasoning=True,
                metadata={
                    "source": "local",
                },
                timestamp=time.time(),
            )

        # -----------------------------------------------------
        # PLANNING
        # -----------------------------------------------------

        if any(
            trigger in query
            for trigger in self.PLANNING_TRIGGERS
        ):
            return Intent(
                original_query=original_query,
                normalized_query=query,
                intent_type="planning",
                confidence=0.92,
                entities=entities,
                requires_memory=True,
                requires_documents=False,
                requires_web=False,
                requires_reasoning=True,
                metadata={
                    "source": "local",
                },
                timestamp=time.time(),
            )

        # -----------------------------------------------------
        # WEB / CURRENT INFORMATION
        # -----------------------------------------------------

        if any(
            trigger in query
            for trigger in self.WEB_TRIGGERS
        ):
            return Intent(
                original_query=original_query,
                normalized_query=query,
                intent_type="research",
                confidence=0.93,
                entities=entities,
                requires_memory=False,
                requires_documents=False,
                requires_web=True,
                requires_reasoning=True,
                metadata={
                    "source": "local",
                    "current_information": True,
                },
                timestamp=time.time(),
            )

        # -----------------------------------------------------
        # SEARCH
        # -----------------------------------------------------

        if any(
            trigger in query
            for trigger in self.SEARCH_TRIGGERS
        ):
            return Intent(
                original_query=original_query,
                normalized_query=query,
                intent_type="research",
                confidence=0.91,
                entities=entities,
                requires_memory=False,
                requires_documents=False,
                requires_web=True,
                requires_reasoning=True,
                metadata={
                    "source": "local",
                },
                timestamp=time.time(),
            )

        # -----------------------------------------------------
        # TOOL / ACTION
        # -----------------------------------------------------

        if any(
            trigger in query
            for trigger in self.TOOL_TRIGGERS
        ):
            return Intent(
                original_query=original_query,
                normalized_query=query,
                intent_type="tool",
                confidence=0.88,
                entities=entities,
                requires_memory=True,
                requires_documents=False,
                requires_web=False,
                requires_reasoning=True,
                metadata={
                    "source": "local",
                },
                timestamp=time.time(),
            )

        # -----------------------------------------------------
        # QUESTIONS
        # -----------------------------------------------------

        question_starters = (
            "what ",
            "why ",
            "how ",
            "who ",
            "where ",
            "when ",
            "which ",
            "can ",
            "could ",
            "would ",
            "should ",
            "is ",
            "are ",
            "do ",
            "does ",
            "did ",
        )

        if (
            query.endswith("?")
            or query.startswith(
                question_starters
            )
        ):
            return Intent(
                original_query=original_query,
                normalized_query=query,
                intent_type="question",
                confidence=0.90,
                entities=entities,
                requires_memory=True,
                requires_documents=False,
                requires_web=False,
                requires_reasoning=True,
                metadata={
                    "source": "local",
                },
                timestamp=time.time(),
            )

        # -----------------------------------------------------
        # GENERAL CONVERSATION
        # -----------------------------------------------------

        return Intent(
            original_query=original_query,
            normalized_query=query,
            intent_type="conversation",
            confidence=0.80,
            entities=entities,
            requires_memory=True,
            requires_documents=False,
            requires_web=False,
            requires_reasoning=False,
            metadata={
                "source": "local",
            },
            timestamp=time.time(),
        )

    # =========================================================
    # SEMANTIC LLM CLASSIFICATION
    # =========================================================

    async def _semantic_intent(
        self,
        original_query: str,
    ) -> Optional[Intent]:

        if not self.llm_router:
            return None

        if not hasattr(
            self.llm_router,
            "chat",
        ):
            return None

        system_prompt = """
You are ARIA's semantic intent classifier.

Classify the USER REQUEST into exactly one category:

- greeting
- follow_up
- memory
- planning
- research
- coding
- tool
- document
- question
- multi_step
- clarification
- conversation

Determine the capabilities required.

Return ONLY valid JSON:

{
  "intent_type": "question",
  "confidence": 0.95,
  "requires_memory": true,
  "requires_documents": false,
  "requires_web": false,
  "requires_reasoning": true,
  "entities": [],
  "action_name": null,
  "action_params": {}
}

Rules:

1. Current/latest/recent/live information normally requires web access.
2. Personal facts and previous conversation normally require memory.
3. Files/PDFs/documents require document processing.
4. Coding/programming requests require reasoning and coding capability.
5. Multi-step tasks require reasoning and planning.
6. Do not answer the user.
7. Do not invent entities.
8. Confidence must be between 0.0 and 1.0.
"""

        try:
            response = await self.llm_router.chat(
                [
                    {
                        "role": "system",
                        "content": system_prompt,
                    },
                    {
                        "role": "user",
                        "content": original_query,
                    },
                ],
                temperature=0.0,
                max_tokens=300,
            )

            cleaned = str(
                response or ""
            ).strip()

            if cleaned.startswith("```"):
                cleaned = re.sub(
                    r"^```(?:json)?\s*",
                    "",
                    cleaned,
                    flags=re.IGNORECASE,
                )

                cleaned = re.sub(
                    r"\s*```$",
                    "",
                    cleaned,
                ).strip()

            data = json.loads(
                cleaned
            )

            intent_type = str(
                data.get(
                    "intent_type",
                    "conversation",
                )
            ).strip().lower()

            confidence = float(
                data.get(
                    "confidence",
                    0.70,
                )
            )

            confidence = max(
                0.0,
                min(
                    confidence,
                    1.0,
                ),
            )

            entities = data.get(
                "entities",
                [],
            )

            if not isinstance(
                entities,
                list,
            ):
                entities = []

            return Intent(
                original_query=original_query,
                normalized_query=self.normalize(
                    original_query
                ),
                intent_type=intent_type,
                confidence=confidence,
                entities=entities,
                requires_memory=bool(
                    data.get(
                        "requires_memory",
                        True,
                    )
                ),
                requires_documents=bool(
                    data.get(
                        "requires_documents",
                        False,
                    )
                ),
                requires_web=bool(
                    data.get(
                        "requires_web",
                        False,
                    )
                ),
                requires_reasoning=bool(
                    data.get(
                        "requires_reasoning",
                        True,
                    )
                ),
                metadata={
                    "source": "llm",
                    "action_name": data.get(
                        "action_name"
                    ),
                    "action_params": data.get(
                        "action_params",
                        {},
                    ),
                },
                timestamp=time.time(),
            )

        except Exception:
            logger.exception(
                "[IntentAnalyzer] Semantic classification failed; using local classifier."
            )

            return None

    # =========================================================
    # PUBLIC ANALYSIS API
    # =========================================================

    async def analyze(
        self,
        query: str,
    ) -> Intent:
        """
        Analyze a request using semantic classification when
        available, with deterministic fallback.

        This method is async because the semantic layer may call
        the LLM router.
        """

        original_query = str(
            query or ""
        )

        normalized_query = self.normalize(
            original_query
        )

        # Fast deterministic cases first.
        local_intent = self._local_intent(
            original_query,
            normalized_query,
        )

        # High-confidence local intents should not be sent
        # unnecessarily to an LLM.
        if local_intent.confidence >= 0.94:
            return self._remember_intent(
                local_intent
            )

        # Let the semantic layer improve ambiguous requests.
        semantic_intent = await self._semantic_intent(
            original_query
        )

        if semantic_intent is not None:

            # Preserve explicit locally detected entities if the
            # semantic model returned none.
            if (
                not semantic_intent.entities
                and local_intent.entities
            ):
                semantic_intent.entities = (
                    local_intent.entities
                )

            return self._remember_intent(
                semantic_intent
            )

        return self._remember_intent(
            local_intent
        )

    # =========================================================
    # TELEMETRY
    # =========================================================

    def history(self) -> list:
        return list(
            self.intent_history
        )

    def last_intent(
        self,
    ) -> Optional[Intent]:

        if not self.intent_history:
            return None

        return self.intent_history[-1]