import logging
import re
from typing import Dict, Any, Optional, List, TYPE_CHECKING

from brain.memory.memory_engine import MemoryEngine

if TYPE_CHECKING:
    from brain.llm.llm_router import LLMRouter

logger = logging.getLogger("aria")


class MemoryConversationManager:
    """
    Handles direct interaction with ARIA's persistent memory.

    Important principle:
    If ARIA already knows the answer from memory, it should answer
    directly without requiring an external LLM.
    """

    def __init__(
        self,
        memory_engine: MemoryEngine,
        llm_router: Optional["LLMRouter"] = None
    ):
        self.memory_engine = memory_engine
        self.llm_router = llm_router

    async def handle(
        self,
        query: str,
        context: Dict[str, Any]
    ) -> str:

        intent = context.get("intent")
        intent_name = (
            getattr(intent, "name", None)
            or str(intent or "memory")
        )

        lower_q = query.lower().strip()

        # -----------------------------------------------------
        # 1. FORGET / DELETE
        # -----------------------------------------------------

        if (
            intent_name == "memory_delete"
            or lower_q.startswith(
                ("forget", "delete", "clear", "remove")
            )
        ):
            return await self._handle_forget(query)

        # -----------------------------------------------------
        # 2. EXPLICIT MEMORY STORE / UPDATE
        # -----------------------------------------------------

        if intent_name in ("memory_store", "memory_update"):

            result = await self.memory_engine.process_and_store(query)

            if not result or not result.get("success"):
                return (
                    "I couldn't save that to memory just now, Sir."
                )

            action_type = str(
                result.get("action", "stored")
            ).lower()

            # -------------------------------------------------
            # Single-memory result
            # -------------------------------------------------

            key = str(
                result.get("key") or ""
            ).strip()

            value = str(
                result.get("value") or ""
            ).strip()

            if key and value:

                readable_key = (
                    key
                    .replace("favorite_", "")
                    .replace("favourite_", "")
                    .replace("_", " ")
                    .strip()
                )

                if action_type == "update":
                    return (
                        f"Updated, Sir. "
                        f"I'll remember that your "
                        f"{readable_key} is {value}."
                    )

                return (
                    f"Understood, Sir. "
                    f"I'll remember that your "
                    f"{readable_key} is {value}."
                )

            # -------------------------------------------------
            # Multiple-memory result
            # -------------------------------------------------

            memories = result.get("memories")

            if isinstance(memories, list):

                stored = []

                for memory in memories:

                    if not isinstance(memory, dict):
                        continue

                    memory_key = str(
                        memory.get("key") or ""
                    ).strip()

                    memory_value = str(
                        memory.get("value") or ""
                    ).strip()

                    if not memory_key or not memory_value:
                        continue

                    readable_key = (
                        memory_key
                        .replace("favorite_", "")
                        .replace("favourite_", "")
                        .replace("_", " ")
                        .strip()
                    )

                    stored.append(
                        f"{readable_key}: {memory_value}"
                    )

                if len(stored) == 1:
                    return (
                        f"Understood, Sir. "
                        f"I'll remember {stored[0]}."
                    )

                if stored:
                    return (
                        "Understood, Sir. I've remembered "
                        "those details."
                    )

            # -------------------------------------------------
            # Storage succeeded, but MemoryEngine did not
            # expose the stored fields in its result.
            # Never generate an empty acknowledgement.
            # -------------------------------------------------

            if action_type == "update":
                return (
                    "Updated, Sir. I've revised that "
                    "in my memory."
                )

            return (
                "Understood, Sir. I've saved that "
                "to memory."
            )

        # -----------------------------------------------------
        # 3. MEMORY RECALL
        #
        # Reuse memories already retrieved by CognitiveCore.
        # Only query MemoryEngine directly when this manager
        # was called without pre-retrieved memory context.
        # -----------------------------------------------------

        memories = context.get("memory") or []

        if memories:

            logger.info(
                "[MemoryConversationManager] Using %d "
                "pre-retrieved memories from context.",
                len(memories),
            )

        else:

            logger.info(
                "[MemoryConversationManager] No memories supplied "
                "in context; falling back to direct retrieval."
            )

            memories = await self.memory_engine.retrieve(query)

        if memories:

            logger.info(
                "[MemoryConversationManager] Direct memory recall "
                "found %d memories.",
                len(memories)
            )

            direct_answer = self._build_direct_answer(
                query,
                memories
            )

            if direct_answer:
                logger.info(
                    "[MemoryConversationManager] Answered directly "
                    "from persistent memory."
                )

                return direct_answer

            logger.info(
                "[MemoryConversationManager] Relevant memories exist, "
                "but deterministic recall could not answer confidently. "
                "Attempting semantic memory reasoning."
            )

            # -------------------------------------------------
            # SEMANTIC MEMORY FALLBACK
            #
            # Deterministic matching could not understand the
            # relationship between the user's wording and the
            # retrieved memories. Let the LLM interpret those
            # memories without allowing it to invent facts.
            # -------------------------------------------------

            if self.llm_router:

                try:

                    semantic_answer = (
                        await self.llm_router.answer_from_memories(
                            query=query,
                            memories=memories
                        )
                    )

                    if semantic_answer:

                        semantic_answer = str(
                            semantic_answer
                        ).strip()

                        # Defensive guard against empty or explicit
                        # insufficient-evidence responses.
                        insufficient_answers = {
                            "",
                            "none",
                            "null",
                            "unknown",
                            "insufficient_evidence",
                            "insufficient evidence",
                            "not_found",
                            "not found",
                        }

                        if (
                            semantic_answer.lower()
                            not in insufficient_answers
                        ):

                            logger.info(
                                "[MemoryConversationManager] Answered through "
                                "semantic persistent-memory reasoning."
                            )

                            return semantic_answer

                    logger.info(
                        "[MemoryConversationManager] Semantic memory "
                        "reasoning found insufficient evidence."
                    )

                except Exception:

                    logger.exception(
                        "[MemoryConversationManager] Semantic memory "
                        "reasoning failed."
                    )

            else:

                logger.warning(
                    "[MemoryConversationManager] Semantic memory reasoning "
                    "unavailable because LLMRouter is not connected."
                )

            # -------------------------------------------------
            # RETRIEVAL != KNOWLEDGE
            #
            # MemoryEngine may always return nearest-neighbour
            # candidates. Reaching this point means none of
            # those candidates actually answered the question.
            # -------------------------------------------------

            logger.info(
                "[MemoryConversationManager] Retrieved memory "
                "candidates did not contain a grounded answer."
            )

            key_guess = self._guess_key_from_query(
                lower_q
            )

            if key_guess:
                return (
                    f"I don't remember your "
                    f"{key_guess} yet, Sir."
                )

            return (
                "I don't have that information "
                "in memory yet, Sir."
            )

        # -----------------------------------------------------
        # 4. NOTHING FOUND
        # -----------------------------------------------------

        key_guess = self._guess_key_from_query(
            lower_q
        )

        if key_guess:
            return (
                f"I don't remember your {key_guess} yet, Sir."
            )

        return (
            "I don't have that information in memory yet, Sir."
        )

    # =========================================================
    # DIRECT MEMORY ANSWERING
    # =========================================================

    def _build_direct_answer(
        self,
        query: str,
        memories: List[Dict[str, Any]]
    ) -> Optional[str]:
        """
        Produces direct answers from retrieved memories without
        requiring Groq, Gemini or another external LLM.

        This handles high-confidence personal-memory questions.
        More complex reasoning can still be delegated elsewhere.
        """

        q = query.lower().strip()

        usable = []

        for memory in memories:

            if not isinstance(memory, dict):
                continue

            key = str(
                memory.get("key", "")
            ).strip().lower()

            value = str(
                memory.get("value", "")
            ).strip()

            if key and value:
                usable.append(
                    {
                        "key": key,
                        "value": value,
                        "memory": memory
                    }
                )

        if not usable:
            return None

        # -----------------------------------------------------
        # NAME
        # -----------------------------------------------------

        if self._contains_any(
            q,
            (
                "my name",
                "what am i called",
                "who am i"
            )
        ):

            value = self._find_value(
                usable,
                ("name", "user_name", "full_name")
            )

            if value:
                return f"Your name is {value}, Sir."

        # -----------------------------------------------------
        # COUNTRY / STUDY DESTINATION
        # -----------------------------------------------------

        if self._contains_any(
            q,
            (
                "which country",
                "what country",
                "country was i interested",
                "country am i interested",
                "study destination",
                "masters destination",
                "master's destination",
                "postgraduate location",
                "where do i want to study",
                "where am i planning to study"
            )
        ):

            value = self._find_value(
                usable,
                (
                    "planned_postgraduate_location",
                    "postgraduate_location",
                    "study_destination",
                    "preferred_country",
                    "country"
                )
            )

            if value:
                return f"{value}, Sir."

        # -----------------------------------------------------
        # CURRENT EDUCATION / YEAR
        # -----------------------------------------------------

        if self._contains_any(
            q,
            (
                "what year",
                "which year",
                "current year",
                "education level",
                "what am i studying",
                "what do i study",
                "my degree",
                "current degree"
            )
        ):

            value = self._find_value(
                usable,
                (
                    "current_education_level",
                    "current_degree",
                    "education_level",
                    "degree"
                )
            )

            if value:
                return f"You're currently in {value}, Sir."

        # -----------------------------------------------------
        # PLAN AFTER B.TECH / POSTGRADUATE PLAN
        # -----------------------------------------------------

        if (
            "after b.tech" in q
            or "after btech" in q
            or self._contains_any(
                q,
                (
                    "my future plan",
                    "my plan after",
                    "postgraduate plan",
                    "masters plan",
                    "master's plan"
                )
            )
        ):

            degree = self._find_value(
                usable,
                (
                    "planned_postgraduate_degree",
                    "postgraduate_degree"
                )
            )

            location = self._find_value(
                usable,
                (
                    "planned_postgraduate_location",
                    "postgraduate_location",
                    "study_destination"
                )
            )

            if degree and location:
                return (
                    f"You're planning to pursue your "
                    f"{degree} in {location} after B.Tech, Sir."
                )

            if degree:
                return (
                    f"You're planning to pursue your "
                    f"{degree} after B.Tech, Sir."
                )

            if location:
                return (
                    f"You're planning to study in "
                    f"{location} after B.Tech, Sir."
                )

        # -----------------------------------------------------
        # EDUCATION PREFERENCE / PRIORITY
        # -----------------------------------------------------

        if self._contains_any(
            q,
            (
                "education preference",
                "education priority",
                "why italy",
                "why did i choose italy",
                "why am i interested in italy",
                "why i chose italy",
                "what do i want from education"
            )
        ):

            preference = self._find_value(
                usable,
                (
                    "education_preference",
                    "education_priority"
                )
            )

            if preference:
                return (
                    f"Your priority is {preference}, Sir."
                )

        # -----------------------------------------------------
        # EXACT / CLOSE KEY MATCH
        #
        # IMPORTANT:
        # Retrieved memories are only candidates. A memory must
        # actually match the subject of the user's question
        # before ARIA may answer from it.
        # -----------------------------------------------------

        normalized_query = self._normalize(q)

        query_words = self._meaningful_words(
            normalized_query
        )

        best = None
        best_score = 0.0

        for item in usable:

            normalized_key = self._normalize(
                item["key"]
            )

            key_words = self._meaningful_words(
                normalized_key
            )

            if not key_words or not query_words:
                continue

            shared_words = (
                key_words.intersection(query_words)
            )

            # Generic words such as "favorite", "my", "plan",
            # etc. must never be enough to select a memory.
            meaningful_shared = {
                word
                for word in shared_words
                if word not in self._generic_memory_words()
            }

            if not meaningful_shared:
                continue

            # How much of the memory key is actually represented
            # in the user's question?
            specific_key_words = {
                word
                for word in key_words
                if word not in self._generic_memory_words()
            }

            if not specific_key_words:
                continue

            coverage = (
                len(meaningful_shared)
                / len(specific_key_words)
            )

            # Prefer memories whose specific subject is strongly
            # represented in the query.
            if coverage > best_score:
                best = item
                best_score = coverage

        # Require strong subject agreement.
        #
        # Example:
        # query: "What is my favorite movie?"
        # key:   "favorite_movie"
        # -> movie matches -> valid
        #
        # query: "What is my favorite dinosaur?"
        # key:   "favorite_movie"
        # -> only "favorite" overlaps, which is generic
        # -> rejected
        if best and best_score >= 0.75:

            readable_key = (
                best["key"]
                .replace("favorite_", "")
                .replace("favourite_", "")
                .replace("_", " ")
            )

            return (
                f"Your {readable_key} is "
                f"{best['value']}, Sir."
            )

        # Never blindly return the nearest retrieved memory.
        return None

    # =========================================================
    # HELPERS
    # =========================================================

    def _generic_memory_words(self) -> set:
        """
        Words that describe the relationship to a memory rather
        than the actual subject of the memory.

        These words must not be enough by themselves to prove
        that a retrieved memory answers the user's question.
        """

        return {
            "my",
            "me",
            "i",
            "am",
            "is",
            "are",
            "was",
            "were",
            "what",
            "which",
            "who",
            "where",
            "when",
            "why",
            "how",
            "do",
            "did",
            "does",
            "have",
            "has",
            "had",
            "the",
            "a",
            "an",
            "of",
            "to",
            "for",
            "in",
            "on",
            "at",
            "about",
            "remember",
            "recall",
            "memory",
            "favorite",
            "favourite",
            "preferred",
            "preference",
        }

    def _meaningful_words(
        self,
        text: str
    ) -> set:
        """
        Converts text into normalized words for deterministic
        memory-subject matching.
        """

        normalized = self._normalize(text)

        return {
            word
            for word in normalized.split()
            if word
        }

    def _find_value(
        self,
        memories: List[Dict[str, Any]],
        preferred_keys
    ) -> Optional[str]:

        # Exact key first
        for preferred in preferred_keys:
            for item in memories:
                if item["key"] == preferred:
                    return item["value"]

        # Partial key fallback
        for preferred in preferred_keys:
            for item in memories:
                if (
                    preferred in item["key"]
                    or item["key"] in preferred
                ):
                    return item["value"]

        return None

    def _contains_any(
        self,
        text: str,
        phrases
    ) -> bool:

        return any(
            phrase in text
            for phrase in phrases
        )

    def _normalize(
        self,
        text: str
    ) -> str:

        text = text.lower()
        text = text.replace("_", " ")

        text = re.sub(
            r"[^a-z0-9\s]",
            " ",
            text
        )

        return re.sub(
            r"\s+",
            " ",
            text
        ).strip()

    # =========================================================
    # DELETE
    # =========================================================

    async def _handle_forget(
        self,
        query: str
    ) -> str:

        try:

            success = await self.memory_engine.delete_memory(
                query
            )

            if success:
                return (
                    "Done, Sir. I've removed that from memory."
                )

            return (
                "I couldn't find a matching memory to remove, Sir."
            )

        except Exception:

            logger.exception(
                "[MemoryConversationManager] "
                "Failed to delete memory."
            )

            return (
                "I couldn't update my memory just now, Sir."
            )

    # =========================================================
    # FAILED RECALL SUBJECT
    # =========================================================

    def _guess_key_from_query(
        self,
        query: str
    ) -> Optional[str]:

        normalized = self._normalize(
            query
        )

        patterns = (
            r"(?:what is|what s|whats)\s+my\s+(.+)",
            r"(?:which is)\s+my\s+(.+)",
            r"(?:do you remember)\s+my\s+(.+)",
            r"(?:can you remember)\s+my\s+(.+)",
            r"(?:recall)\s+my\s+(.+)",
        )

        for pattern in patterns:

            match = re.search(
                pattern,
                normalized
            )

            if not match:
                continue

            subject = match.group(1).strip()

            subject = re.sub(
                r"\b(favorite|favourite)\b",
                "",
                subject
            )

            subject = re.sub(
                r"\s+",
                " ",
                subject
            ).strip()

            if subject:
                return subject

        return None
