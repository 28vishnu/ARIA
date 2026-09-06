import json
import logging
import re
from typing import Dict, Any, Optional, List, TYPE_CHECKING, Tuple
from datetime import datetime, timezone

from brain.memory.memory_engine import MemoryEngine

if TYPE_CHECKING:
    from brain.llm.llm_router import LLMRouter

logger = logging.getLogger("aria")


class MemoryConversationManager:
    """
    Handles direct interaction with ARIA's persistent memory.

    Phase 11 integration behavior:
    - Pure memory requests may be answered directly.
    - Memory operations embedded inside compound requests are
      handled without terminating the wider cognitive pipeline.
    - Retrieval candidates are filtered before being treated as facts.
    - Sensitive information is never exposed.
    - Episodic memory remains separate from durable personal memory.

    Important principle:
    If ARIA already knows the answer from memory, it should answer
    directly without requiring an external LLM — unless the request
    is part of a larger compound task.
    """

    VERSION = "11.1"

    def __init__(
        self,
        memory_engine: MemoryEngine,
        llm_router: Optional["LLMRouter"] = None
    ):
        self.memory_engine = memory_engine
        self.llm_router = llm_router

        # Phase 5 — persistent episodic memory.
        # Keep episodes separate from personal/factual memory.
        self.episode_col = None

        try:
            db = getattr(
                memory_engine,
                "db",
                None,
            )

            if db is not None:
                self.episode_col = db[
                    "memory_episodes"
                ]

        except Exception:
            logger.exception(
                "[MemoryConversationManager] "
                "Failed to initialize episodic memory."
            )

    # =========================================================
    # MAIN MEMORY HANDLER
    # =========================================================

    async def handle(
        self,
        query: str,
        context: Dict[str, Any]
    ) -> str:
        """
        Handle a memory-related request.

        A crucial Phase-11 rule is that memory handling must not
        accidentally terminate a larger request.

        Example:

            "What do you remember about me?"

        is terminal and may return a memory answer.

        But:

            "Tell me what you remember about me and make me
             a Python study plan."

        is compound. Memory may contribute context, but the
        CognitiveCore pipeline must continue into planning.

        Context flags exposed by this method:

            memory_handled
            memory_terminal
            memory_result
            memory_compound_request
            memory_operation
        """

        if not isinstance(context, dict):
            context = {}

        query = str(query or "").strip()

        intent = context.get("intent")
        intent_name = self._get_intent_name(intent)

        lower_q = query.lower().strip()
        normalized_q = self._normalize(query)

        # -----------------------------------------------------
        # INITIALIZE PIPELINE FLAGS
        # -----------------------------------------------------

        context["memory_handled"] = False
        context["memory_terminal"] = False
        context["memory_result"] = None
        context["memory_compound_request"] = False
        context["memory_operation"] = None

        # -----------------------------------------------------
        # EMPTY QUERY
        # -----------------------------------------------------

        if not query:
            context["memory_handled"] = True
            context["memory_terminal"] = True
            return (
                "I don't have a memory request to process, Sir."
            )

        # -----------------------------------------------------
        # COMPOUND REQUEST DETECTION
        #
        # This MUST happen before direct memory answering.
        #
        # A memory route must not consume a request that also
        # asks ARIA to plan, explain, execute, search, reason,
        # or perform another task.
        # -----------------------------------------------------

        compound_request = self._is_compound_memory_request(
            query,
            intent_name=intent_name,
            context=context,
        )

        context["memory_compound_request"] = compound_request

        if compound_request:
            logger.info(
                "[MemoryConversationManager] Compound memory request "
                "detected; memory handling will not terminate pipeline."
            )

        # -----------------------------------------------------
        # SENSITIVE INFORMATION
        #
        # Security-sensitive requests are terminal regardless
        # of whether they are compound. Never allow downstream
        # components to receive sensitive memory candidates.
        # -----------------------------------------------------

        if self._is_sensitive_query(lower_q):
            context["memory_handled"] = True
            context["memory_terminal"] = True
            context["memory_operation"] = "sensitive_refusal"

            response = (
                "I can't provide or expose sensitive identity or security "
                "information, Sir."
            )

            context["memory_result"] = response
            return response

        # -----------------------------------------------------
        # 1. FORGET / DELETE
        # -----------------------------------------------------

        if (
            intent_name == "memory_delete"
            or lower_q.startswith(
                ("forget ", "forget", "delete ", "delete",
                 "clear ", "clear", "remove ", "remove")
            )
        ):
            context["memory_operation"] = "delete"

            response = await self._handle_forget(query)

            context["memory_handled"] = True

            # Deletion inside a larger request should not prevent
            # downstream work from continuing.
            if compound_request:
                context["memory_terminal"] = False
                context["memory_result"] = response

                logger.info(
                    "[MemoryConversationManager] Memory deletion completed "
                    "inside compound request; continuing pipeline."
                )

                return ""

            context["memory_terminal"] = True
            context["memory_result"] = response
            return response

        # -----------------------------------------------------
        # 2. EXPLICIT MEMORY STORE / UPDATE
        # -----------------------------------------------------

        if intent_name in ("memory_store", "memory_update"):
            context["memory_operation"] = "store"

            result = await self.memory_engine.process_and_store(
                query
            )

            if not result or not result.get("success"):
                response = (
                    "I couldn't save that to memory just now, Sir."
                )

                context["memory_handled"] = True

                if compound_request:
                    context["memory_terminal"] = False
                    context["memory_result"] = response
                    return ""

                context["memory_terminal"] = True
                context["memory_result"] = response
                return response

            response = self._build_store_response(
                result
            )

            context["memory_handled"] = True
            context["memory_result"] = response

            # -------------------------------------------------
            # CRITICAL PHASE-11 BEHAVIOR
            #
            # A successful memory write inside a compound
            # request must NOT terminate CognitiveCore.
            # -------------------------------------------------

            if compound_request:
                context["memory_terminal"] = False

                logger.info(
                    "[MemoryConversationManager] Memory stored successfully "
                    "inside compound request; continuing cognitive pipeline."
                )

                return ""

            context["memory_terminal"] = True
            return response

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

            try:
                memories = await self.memory_engine.retrieve(
                    query
                )
            except Exception:
                logger.exception(
                    "[MemoryConversationManager] Direct memory retrieval failed."
                )
                memories = []

        # -----------------------------------------------------
        # FILTER CANDIDATES
        # -----------------------------------------------------

        memories = self._filter_relevant_memories(
            query,
            memories,
        )

        # Keep filtered memories available to the rest of the
        # cognitive pipeline. This is particularly important for
        # compound requests.
        context["memory"] = memories

        # -----------------------------------------------------
        # COMPOUND RECALL
        #
        # Do NOT build a direct final answer here.
        #
        # Instead, make the safe memory context available to
        # CognitiveCore so the rest of the request can continue.
        # -----------------------------------------------------

        if compound_request:
            context["memory_handled"] = bool(memories)
            context["memory_terminal"] = False
            context["memory_operation"] = "recall"

            if memories:
                logger.info(
                    "[MemoryConversationManager] Preserved %d safe memories "
                    "for compound cognitive processing.",
                    len(memories),
                )
            else:
                logger.info(
                    "[MemoryConversationManager] No relevant memories "
                    "available for compound request."
                )

            # Empty string intentionally means:
            # "memory manager did not produce the final response;
            # continue CognitiveCore."
            return ""

        # -----------------------------------------------------
        # 4. PURE MEMORY RECALL
        # -----------------------------------------------------

        if memories:
            logger.info(
                "[MemoryConversationManager] Direct memory recall "
                "found %d memories.",
                len(memories),
            )

            direct_answer = self._build_direct_answer(
                query,
                memories,
            )

            if direct_answer:
                logger.info(
                    "[MemoryConversationManager] Answered directly "
                    "from persistent memory."
                )

                context["memory_handled"] = True
                context["memory_terminal"] = True
                context["memory_operation"] = "recall"
                context["memory_result"] = direct_answer

                return direct_answer

            logger.info(
                "[MemoryConversationManager] Relevant memories exist, "
                "but deterministic recall could not answer confidently. "
                "Attempting semantic memory reasoning."
            )

            # -------------------------------------------------
            # SEMANTIC MEMORY FALLBACK
            # -------------------------------------------------

            if self.llm_router:
                try:
                    semantic_answer = (
                        await self.llm_router.answer_from_memories(
                            query=query,
                            memories=memories,
                        )
                    )

                    if semantic_answer:
                        semantic_answer = str(
                            semantic_answer
                        ).strip()

                        if self._is_valid_memory_answer(
                            semantic_answer
                        ):
                            logger.info(
                                "[MemoryConversationManager] Answered through "
                                "semantic persistent-memory reasoning."
                            )

                            context["memory_handled"] = True
                            context["memory_terminal"] = True
                            context["memory_operation"] = "semantic_recall"
                            context["memory_result"] = semantic_answer

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
            # -------------------------------------------------

            key_guess = self._guess_key_from_query(
                lower_q
            )

            context["memory_handled"] = True
            context["memory_terminal"] = True
            context["memory_operation"] = "recall"

            if key_guess:
                response = (
                    f"I don't remember your "
                    f"{key_guess} yet, Sir."
                )
            else:
                response = (
                    "I don't have that information "
                    "in memory yet, Sir."
                )

            context["memory_result"] = response
            return response

        # -----------------------------------------------------
        # 5. NOTHING FOUND
        # -----------------------------------------------------

        key_guess = self._guess_key_from_query(
            lower_q
        )

        context["memory_handled"] = True
        context["memory_terminal"] = True
        context["memory_operation"] = "recall"

        if key_guess:
            response = (
                f"I don't remember your {key_guess} yet, Sir."
            )
        else:
            response = (
                "I don't have that information in memory yet, Sir."
            )

        context["memory_result"] = response
        return response

    # =========================================================
    # COMPOUND REQUEST DETECTION
    # =========================================================

    def _is_compound_memory_request(
        self,
        query: str,
        intent_name: str = "",
        context: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Determine whether a memory request is embedded inside
        a larger task.

        This deliberately avoids treating every sentence containing
        "and" as compound.

        Strong secondary-task signals are preferred.
        """

        q = self._normalize(query)

        if not q:
            return False

        # -----------------------------------------------------
        # Explicit downstream task markers
        # -----------------------------------------------------

        secondary_task_phrases = (
            # Planning
            "make a plan",
            "create a plan",
            "give me a plan",
            "build a plan",
            "short plan",
            "study plan",
            "learning plan",
            "roadmap",
            "make a roadmap",
            "create a roadmap",

            # Reasoning / explanation
            "explain",
            "explain why",
            "tell me why",
            "analyze",
            "analyse",
            "compare",
            "summarize",
            "summarise",
            "what should i do",
            "what do i do first",
            "what should i do first",
            "what is the next step",
            "what are the next steps",

            # Execution / actions
            "do this",
            "do that",
            "help me do",
            "execute",
            "run",
            "open",
            "send",
            "create",
            "write",
            "generate",

            # Search / current information
            "search for",
            "search the web",
            "look up",
            "find information",
            "find me",
            "latest",
            "current information",
            "check online",

            # Coding
            "write code",
            "write python",
            "write javascript",
            "code this",
            "fix this code",
            "debug this",

            # Multi-step workflow language
            "then",
            "after that",
            "and then",
            "also",
            "as well as",
            "followed by",
            "next",
        )

        if any(
            phrase in q
            for phrase in secondary_task_phrases
        ):
            # A lone "then" or "also" is not enough unless
            # there is a recognizable memory operation.
            if (
                self._has_explicit_memory_operation(q)
                or self._looks_like_memory_intent(intent_name)
            ):
                return True

        # -----------------------------------------------------
        # Structural multi-task detection
        #
        # Example:
        # "remember X and make Y"
        # "tell me X and explain Y"
        # -----------------------------------------------------

        if self._has_explicit_memory_operation(q):
            if re.search(
                r"\b(?:and|then|also|after that|followed by|next)\b",
                q,
            ):
                return True

        # -----------------------------------------------------
        # Existing CognitiveCore orchestration state
        # -----------------------------------------------------

        if isinstance(context, dict):
            orchestration = context.get(
                "orchestration"
            )

            if isinstance(orchestration, dict):
                if (
                    orchestration.get("multi_step")
                    or orchestration.get("compound")
                    or orchestration.get("requires_planning")
                ):
                    return True

            if context.get("requires_planning"):
                return True

            if context.get("multi_step"):
                return True

        return False

    def _has_explicit_memory_operation(
        self,
        query: str
    ) -> bool:
        """Return True when the query explicitly asks ARIA to use memory."""
        q = self._normalize(query)

        memory_phrases = (
            "remember",
            "memorize",
            "save this",
            "save that",
            "store this",
            "store that",
            "keep this in memory",
            "keep that in memory",
            "don't forget",
            "do not forget",
            "forget",
            "delete from memory",
            "remove from memory",
            "clear from memory",
            "what do you remember",
            "what do you know about me",
            "what have you remembered",
            "what have you learned about me",
            "tell me what you remember",
            "tell me what you know about me",
            "recall my",
            "do you remember my",
            "can you remember my",
        )

        return any(
            phrase in q
            for phrase in memory_phrases
        )

    def _looks_like_memory_intent(
        self,
        intent_name: str
    ) -> bool:
        return str(intent_name or "").strip().lower() in {
            "memory",
            "memory_store",
            "memory_update",
            "memory_delete",
            "memory_recall",
            "memory_query",
        }

    def _get_intent_name(
        self,
        intent: Any
    ) -> str:
        """Safely extract an intent name from object/dict/string forms."""

        if intent is None:
            return "memory"

        if isinstance(intent, dict):
            value = (
                intent.get("name")
                or intent.get("intent")
                or intent.get("intent_name")
            )

            if value:
                return str(value).strip().lower()

        value = getattr(
            intent,
            "name",
            None,
        )

        if value:
            return str(value).strip().lower()

        text = str(intent).strip()

        return text.lower() if text else "memory"

    # =========================================================
    # MEMORY STORE RESPONSE
    # =========================================================

    def _build_store_response(
        self,
        result: Dict[str, Any]
    ) -> str:
        """
        Build a clean acknowledgement from MemoryEngine output.
        """

        action_type = str(
            result.get("action", "stored")
        ).lower()

        key = str(
            result.get("key") or ""
        ).strip()

        value = str(
            result.get("value") or ""
        ).strip()

        if key and value:
            readable_key = self._readable_memory_key(
                key
            )

            if action_type == "update":
                return (
                    f"Updated, Sir. I'll remember that your "
                    f"{readable_key} is {value}."
                )

            return (
                f"Understood, Sir. I'll remember that your "
                f"{readable_key} is {value}."
            )

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

                if (
                    not memory_key
                    or not memory_value
                    or self._is_sensitive_memory(memory)
                ):
                    continue

                stored.append(
                    f"{self._readable_memory_key(memory_key)}: "
                    f"{memory_value}"
                )

            if len(stored) == 1:
                return (
                    f"Understood, Sir. I'll remember "
                    f"{stored[0]}."
                )

            if stored:
                return (
                    "Understood, Sir. I've remembered "
                    "those details."
                )

        if action_type == "update":
            return (
                "Updated, Sir. I've revised that "
                "in my memory."
            )

        return (
            "Understood, Sir. I've saved that "
            "to memory."
        )

    # =========================================================
    # MEMORY ANSWER VALIDATION
    # =========================================================

    def _is_valid_memory_answer(
        self,
        answer: str
    ) -> bool:
        """
        Reject empty or explicit insufficient-evidence responses.

        Also reject obvious raw JSON/object leakage from the memory
        reasoning layer.
        """

        text = str(answer or "").strip()

        if not text:
            return False

        normalized = self._normalize(text)

        insufficient_answers = {
            "",
            "none",
            "null",
            "unknown",
            "insufficient evidence",
            "insufficient_evidence",
            "not found",
            "not_found",
            "no information",
            "no relevant information",
        }

        if normalized in insufficient_answers:
            return False

        # Prevent raw internal memory structures from being exposed.
        if (
            text.startswith("{")
            and text.endswith("}")
        ):
            try:
                json.loads(text)
                return False
            except Exception:
                pass

        if (
            text.startswith("[")
            and text.endswith("]")
        ):
            try:
                json.loads(text)
                return False
            except Exception:
                pass

        return True

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

        q = self._normalize(query)

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

            if (
                key
                and value
                and not self._is_sensitive_memory(memory)
            ):
                usable.append(
                    {
                        "key": key,
                        "value": value,
                        "memory": memory,
                    }
                )

        if not usable:
            return None

        # -----------------------------------------------------
        # GENERAL MEMORY SUMMARY
        # -----------------------------------------------------

        if self._is_broad_memory_query(q):
            return self._build_broad_memory_response(
                usable
            )

        # -----------------------------------------------------
        # NAME
        # -----------------------------------------------------

        if self._contains_any(
            q,
            (
                "my name",
                "what am i called",
                "who am i",
            )
        ):
            value = self._find_value(
                usable,
                ("name", "user_name", "full_name"),
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
                "where am i planning to study",
            )
        ):
            value = self._find_value(
                usable,
                (
                    "planned_postgraduate_location",
                    "postgraduate_location",
                    "study_destination",
                    "preferred_country",
                    "country",
                ),
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
                "current degree",
            )
        ):
            value = self._find_value(
                usable,
                (
                    "current_education_level",
                    "current_degree",
                    "education_level",
                    "degree",
                ),
            )

            if value:
                return f"You're currently in {value}, Sir."

        # -----------------------------------------------------
        # PLAN AFTER B.TECH / POSTGRADUATE PLAN
        # -----------------------------------------------------

        if (
            "after b tech" in q
            or "after btech" in q
            or self._contains_any(
                q,
                (
                    "my future plan",
                    "my plan after",
                    "postgraduate plan",
                    "masters plan",
                    "master's plan",
                ),
            )
        ):
            degree = self._find_value(
                usable,
                (
                    "planned_postgraduate_degree",
                    "postgraduate_degree",
                ),
            )

            location = self._find_value(
                usable,
                (
                    "planned_postgraduate_location",
                    "postgraduate_location",
                    "study_destination",
                ),
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
                "what do i want from education",
            )
        ):
            preference = self._find_value(
                usable,
                (
                    "education_preference",
                    "education_priority",
                ),
            )

            if preference:
                return (
                    f"Your priority is {preference}, Sir."
                )

        # -----------------------------------------------------
        # EXACT / CLOSE KEY MATCH
        # -----------------------------------------------------

        normalized_query = self._normalize(q)

        original_query_words = self._meaningful_words(
            normalized_query
        )

        normalized_query_words = {
            self._subject_alias(word)
            for word in original_query_words
        }

        best = None
        best_score = 0.0

        for item in usable:
            normalized_key = self._normalize(
                item["key"]
            )

            original_key_words = self._meaningful_words(
                normalized_key
            )

            if (
                not original_key_words
                or not normalized_query_words
            ):
                continue

            key_words = {
                self._subject_alias(word)
                for word in original_key_words
            }

            shared_words = (
                key_words.intersection(
                    normalized_query_words
                )
            )

            meaningful_shared = {
                word
                for word in shared_words
                if word not in self._generic_memory_words()
            }

            if not meaningful_shared:
                continue

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

            # Add a small query-coverage component so that a
            # candidate matching one generic portion of a long
            # query cannot dominate another candidate.
            specific_query_words = {
                word
                for word in normalized_query_words
                if word not in self._generic_memory_words()
            }

            query_coverage = (
                len(meaningful_shared)
                / max(1, len(specific_query_words))
            )

            score = (
                coverage * 0.70
                + query_coverage * 0.30
            )

            if score > best_score:
                best = item
                best_score = score

        if best and best_score >= 0.75:
            readable_key = self._readable_memory_key(
                best["key"]
            )

            return (
                f"Your {readable_key} is "
                f"{best['value']}, Sir."
            )

        # Never blindly return the nearest retrieved memory.
        return None

    # =========================================================
    # BROAD MEMORY RESPONSE
    # =========================================================

    def _build_broad_memory_response(
        self,
        memories: List[Dict[str, Any]]
    ) -> Optional[str]:
        """
        Build a deterministic personal-memory summary.

        Duplicate semantic subjects are collapsed so keys such as
        favorite_color and favorite_colour do not appear as separate
        entries.

        If multiple records contain conflicting values, both values
        are retained rather than silently inventing which one is
        correct.
        """

        groups: Dict[str, List[Tuple[str, str]]] = {}

        for item in memories:
            key = str(
                item.get("key") or ""
            ).strip().lower()

            value = str(
                item.get("value") or ""
            ).strip()

            if (
                not key
                or not value
                or self._is_sensitive_memory(item)
            ):
                continue

            canonical = self._canonical_memory_subject(
                key
            )

            groups.setdefault(
                canonical,
                []
            ).append(
                (key, value)
            )

        if not groups:
            return (
                "I don't have any personal details about "
                "you in memory yet, Sir."
            )

        lines = []

        for canonical, values in groups.items():
            unique_values = []
            seen_values = set()

            for _, value in values:
                normalized_value = self._normalize(
                    value
                )

                if normalized_value in seen_values:
                    continue

                seen_values.add(
                    normalized_value
                )
                unique_values.append(
                    value
                )

            readable_key = self._readable_memory_key(
                canonical
            )

            if len(unique_values) == 1:
                lines.append(
                    f"• {readable_key.capitalize()}: "
                    f"{unique_values[0]}"
                )
            else:
                lines.append(
                    f"• {readable_key.capitalize()}: "
                    + " / ".join(unique_values)
                )

        if not lines:
            return (
                "I don't have any personal details about "
                "you in memory yet, Sir."
            )

        return (
            "Certainly, Sir. Here's what I remember about you:\n\n"
            + "\n".join(lines)
        )

    def _canonical_memory_subject(
        self,
        key: str
    ) -> str:
        """
        Normalize common aliases to one stable semantic subject.
        """

        normalized = self._normalize(
            key
        )

        aliases = {
            "favorite colour": "favorite_color",
            "favourite colour": "favorite_color",
            "favorite color": "favorite_color",
            "favourite color": "favorite_color",

            "favorite movie": "favorite_movie",
            "favourite movie": "favorite_movie",

            "favorite game": "favorite_game",
            "favourite game": "favorite_game",

            "favorite food": "favorite_food",
            "favourite food": "favorite_food",

            "user name": "name",
            "full name": "name",

            "current degree": "current_degree",
            "degree": "current_degree",

            "education level": "current_education_level",

            "study destination": "study_destination",

            "planned postgraduate location":
                "planned_postgraduate_location",

            "postgraduate location":
                "postgraduate_location",
        }

        if normalized in aliases:
            return aliases[normalized]

        return normalized.replace(
            " ",
            "_"
        )

    # =========================================================
    # EPISODIC MEMORY
    # =========================================================

    async def record_episode(
        self,
        query: str,
        response: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Persist a conversation episode.

        Episodic memory stores what happened in an interaction,
        while personal_memory stores durable facts/preferences.
        """

        if self.episode_col is None:
            return False

        try:
            context = context or {}

            intent = context.get("intent")

            if hasattr(intent, "name"):
                intent = intent.name
            elif isinstance(intent, dict):
                intent = (
                    intent.get("name")
                    or intent.get("intent")
                    or ""
                )

            goal = (
                context.get("autonomous_goal")
                or context.get("goal")
            )

            episode = {
                "query": str(
                    query or ""
                ).strip(),
                "response": str(
                    response or ""
                ).strip(),
                "timestamp": datetime.now(
                    timezone.utc
                ),
                "session_id": str(
                    context.get("session_id") or ""
                ),
                "intent": str(
                    intent or ""
                ),
                "goal": (
                    dict(goal)
                    if isinstance(goal, dict)
                    else None
                ),
                "metadata": {
                    "source": "conversation",
                    "schema_version": 1,
                },
            }

            if not episode["query"]:
                return False

            await self.episode_col.insert_one(
                episode
            )

            logger.debug(
                "[MemoryConversationManager] "
                "Recorded episodic memory."
            )

            return True

        except Exception:
            logger.exception(
                "[MemoryConversationManager] "
                "Failed to record episodic memory."
            )
            return False

    async def retrieve_episodes(
        self,
        query: str,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve relevant episodic conversations using:

        1. lexical subject matching,
        2. response/query word overlap,
        3. recency weighting,
        4. deterministic relevance ranking.
        """

        if self.episode_col is None:
            return []

        try:
            limit = max(
                1,
                min(int(limit), 20),
            )

            normalized_query = self._normalize(
                str(query or "")
            )

            query_words = self._meaningful_words(
                normalized_query
            )

            generic_words = self._generic_memory_words()

            candidate_limit = min(
                max(limit * 5, 25),
                100,
            )

            cursor = (
                self.episode_col
                .find({})
                .sort(
                    "timestamp",
                    -1,
                )
                .limit(candidate_limit)
            )

            episodes = await cursor.to_list(
                length=candidate_limit
            )

            if not episodes:
                return []

            now = datetime.now(
                timezone.utc
            )

            ranked = []

            meaningful_query_words = {
                word
                for word in query_words
                if word not in generic_words
            }

            for episode in episodes:
                if not isinstance(episode, dict):
                    continue

                episode_query = str(
                    episode.get("query") or ""
                ).strip()

                episode_response = str(
                    episode.get("response") or ""
                ).strip()

                if not episode_query:
                    continue

                normalized_episode_query = self._normalize(
                    episode_query
                )

                normalized_episode_response = self._normalize(
                    episode_response
                )

                episode_query_words = (
                    self._meaningful_words(
                        normalized_episode_query
                    )
                )

                episode_response_words = (
                    self._meaningful_words(
                        normalized_episode_response
                    )
                )

                if meaningful_query_words:
                    query_overlap = (
                        meaningful_query_words
                        .intersection(
                            episode_query_words
                        )
                    )

                    response_overlap = (
                        meaningful_query_words
                        .intersection(
                            episode_response_words
                        )
                    )

                    query_score = (
                        len(query_overlap)
                        / len(meaningful_query_words)
                    )

                    response_score = (
                        len(response_overlap)
                        / len(meaningful_query_words)
                    )

                    relevance_score = (
                        (query_score * 0.65)
                        + (response_score * 0.35)
                    )
                else:
                    relevance_score = 0.0

                timestamp = episode.get(
                    "timestamp"
                )

                if isinstance(timestamp, datetime):
                    if timestamp.tzinfo is None:
                        timestamp = timestamp.replace(
                            tzinfo=timezone.utc
                        )

                    age_days = max(
                        0.0,
                        (
                            now - timestamp
                        ).total_seconds()
                        / 86400.0,
                    )

                    recency_score = 1.0 / (
                        1.0
                        + (age_days / 30.0)
                    )
                else:
                    recency_score = 0.0

                if meaningful_query_words:
                    final_score = (
                        (relevance_score * 0.75)
                        + (recency_score * 0.25)
                    )
                else:
                    final_score = recency_score

                ranked.append(
                    (
                        final_score,
                        recency_score,
                        episode,
                    )
                )

            ranked.sort(
                key=lambda item: (
                    item[0],
                    item[1],
                ),
                reverse=True,
            )

            results = []

            for (
                _final_score,
                _recency_score,
                episode,
            ) in ranked[:limit]:

                # Copy before removing internal MongoDB identifier.
                clean_episode = dict(
                    episode
                )

                clean_episode.pop(
                    "_id",
                    None,
                )

                results.append(
                    clean_episode
                )

            logger.debug(
                "[MemoryConversationManager] "
                "Retrieved %d ranked episodic memories.",
                len(results),
            )

            return results

        except Exception:
            logger.exception(
                "[MemoryConversationManager] "
                "Failed to retrieve episodic memory."
            )
            return []

    async def consolidate_episodes(
        self,
        episodes: Optional[List[Dict[str, Any]]] = None,
        limit: int = 10,
    ) -> int:
        """
        Promote only durable, explicitly stated information from
        episodic conversations into semantic/personal memory.

        This is intentionally conservative:
        - No episode is promoted blindly.
        - The LLM must identify explicit durable facts/preferences.
        - MemoryEngine remains responsible for actual storage.
        """

        if not self.memory_engine:
            return 0

        try:
            if episodes is None:
                episodes = await self.retrieve_episodes(
                    query="",
                    limit=limit,
                )

            if not episodes:
                return 0

            episodes = [
                episode
                for episode in episodes
                if (
                    isinstance(episode, dict)
                    and episode.get("query")
                    and episode.get("response")
                )
            ][
                :max(
                    1,
                    min(
                        int(limit),
                        20,
                    ),
                )
            ]

            if not episodes:
                return 0

            if not self.llm_router:
                logger.debug(
                    "[MemoryConversationManager] "
                    "Consolidation skipped: LLMRouter unavailable."
                )
                return 0

            conversation_text = []

            for episode in episodes:
                conversation_text.append(
                    "USER: "
                    + str(
                        episode.get("query", "")
                    ).strip()
                )

                conversation_text.append(
                    "ARIA: "
                    + str(
                        episode.get("response", "")
                    ).strip()
                )

            prompt = f"""
Review the following past ARIA conversations.

Identify ONLY information that is:
1. explicitly stated by the user,
2. about the user personally,
3. likely to remain useful over time,
4. a stable preference, fact, plan, goal, or recurring choice.

Do NOT infer, guess, or invent anything.

Do NOT include:
- temporary situations,
- one-time questions,
- casual conversation,
- facts about other people,
- information that exists only in ARIA's response,
- uncertain conclusions,
- sensitive identity/security information.

Return ONLY a JSON array.

Each item must have:
{{
    "key": "short_snake_case_key",
    "value": "concise value"
}}

If there is nothing suitable, return [].

CONVERSATIONS:
{chr(10).join(conversation_text)}
"""

            answer = await self.llm_router.answer_from_memories(
                query=prompt,
                memories=[],
            )

            if not answer:
                return 0

            text = str(
                answer
            ).strip()

            if text.startswith("```"):
                text = re.sub(
                    r"^```(?:json)?\s*",
                    "",
                    text,
                    flags=re.IGNORECASE,
                )

                text = re.sub(
                    r"\s*```$",
                    "",
                    text,
                ).strip()

            try:
                candidates = json.loads(
                    text
                )
            except Exception:
                logger.warning(
                    "[MemoryConversationManager] "
                    "Consolidation returned invalid JSON."
                )
                return 0

            if not isinstance(
                candidates,
                list,
            ):
                return 0

            stored_count = 0

            for item in candidates:
                if not isinstance(item, dict):
                    continue

                key = str(
                    item.get("key") or ""
                ).strip()

                value = str(
                    item.get("value") or ""
                ).strip()

                if not key or not value:
                    continue

                if not re.fullmatch(
                    r"[a-z0-9]+(?:_[a-z0-9]+)*",
                    key.lower(),
                ):
                    continue

                if len(key) > 100:
                    continue

                if len(value) > 500:
                    continue

                if self._is_sensitive_memory(
                    {
                        "key": key,
                        "value": value,
                    }
                ):
                    continue

                result = await self.memory_engine.process_and_store(
                    f"Remember this about me: {key} is {value}"
                )

                if result and result.get("success"):
                    stored_count += 1

            if stored_count:
                logger.info(
                    "[MemoryConversationManager] "
                    "Consolidated %d durable memories from episodes.",
                    stored_count,
                )

            return stored_count

        except Exception:
            logger.exception(
                "[MemoryConversationManager] "
                "Episode consolidation failed."
            )
            return 0

    # =========================================================
    # MEMORY RELEVANCE FILTER
    # =========================================================

    def _filter_relevant_memories(
        self,
        query: str,
        memories: Any,
    ) -> List[Dict[str, Any]]:
        """
        Keep only memory candidates whose subject agrees with the query.

        Broad memory requests intentionally keep all safe memories.

        Compound requests also receive only safe, filtered memories,
        preventing unrelated nearest-neighbour records from entering
        the main cognitive context.
        """

        if not isinstance(
            memories,
            list,
        ):
            return []

        safe = []

        for memory in memories:
            if not isinstance(
                memory,
                dict,
            ):
                continue

            key = str(
                memory.get("key") or ""
            ).strip()

            value = str(
                memory.get("value") or ""
            ).strip()

            if not key or not value:
                continue

            if self._is_sensitive_memory(
                memory
            ):
                continue

            safe.append(
                memory
            )

        normalized_query = self._normalize(
            query
        )

        if self._is_broad_memory_query(
            normalized_query
        ):
            return self._deduplicate_memory_candidates(
                safe
            )

        if not safe:
            return []

        filtered = []

        for memory in safe:
            score = self._memory_subject_score(
                normalized_query,
                memory,
            )

            if score >= 0.75:
                filtered.append(
                    memory
                )

        logger.debug(
            "[MemoryConversationManager] Relevance filter kept %d/%d "
            "memory candidates for query '%s'.",
            len(filtered),
            len(safe),
            query,
        )

        return self._deduplicate_memory_candidates(
            filtered
        )

    def _deduplicate_memory_candidates(
        self,
        memories: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Remove exact duplicate records while preserving distinct
        values for genuinely conflicting memories.
        """

        results = []
        seen = set()

        for memory in memories:
            key = self._canonical_memory_subject(
                str(
                    memory.get("key") or ""
                )
            )

            value = self._normalize(
                str(
                    memory.get("value") or ""
                )
            )

            marker = (
                key,
                value,
            )

            if marker in seen:
                continue

            seen.add(
                marker
            )
            results.append(
                memory
            )

        return results

    # =========================================================
    # SUBJECT SCORING
    # =========================================================

    def _memory_subject_score(
        self,
        normalized_query: str,
        memory: Dict[str, Any],
    ) -> float:
        """Return deterministic subject agreement between query and memory key."""

        key = self._normalize(
            str(
                memory.get("key") or ""
            )
        )

        if not key or not normalized_query:
            return 0.0

        query_words = self._meaningful_words(
            normalized_query
        )

        key_words = self._meaningful_words(
            key
        )

        generic = self._generic_memory_words()

        query_specific = {
            self._subject_alias(word)
            for word in query_words
            if word not in generic
        }

        key_specific = {
            self._subject_alias(word)
            for word in key_words
            if word not in generic
        }

        if not query_specific or not key_specific:
            return 0.0

        shared = query_specific.intersection(
            key_specific
        )

        if not shared:
            query_subject = self._query_subject_aliases(
                normalized_query
            )

            key_subject = self._key_subject_aliases(
                key
            )

            shared = query_subject.intersection(
                key_subject
            )

        if not shared:
            return 0.0

        coverage = (
            len(shared)
            / max(
                1,
                len(key_specific),
            )
        )

        query_coverage = (
            len(shared)
            / max(
                1,
                len(query_specific),
            )
        )

        if len(key_specific) <= 1:
            return max(
                coverage,
                query_coverage,
            )

        return (
            coverage * 0.70
            + query_coverage * 0.30
        )

    def _query_subject_aliases(
        self,
        query: str
    ) -> set:
        """Map natural-language query phrases to stable memory subjects."""

        q = self._normalize(
            query
        )

        aliases = set()

        groups = {
            "name": (
                "my name",
                "what am i called",
                "who am i",
            ),

            "education": (
                "what am i studying",
                "what do i study",
                "my degree",
                "current degree",
                "education level",
                "what year am i",
                "which year am i",
            ),

            "postgraduate": (
                "masters",
                "master",
                "postgraduate",
                "study destination",
                "where do i want to study",
                "where am i planning to study",
            ),

            "goal": (
                "future plan",
                "my plan",
                "goal",
                "goals",
            ),

            "preference": (
                "preference",
                "priority",
                "what do i want from education",
            ),

            "favorite_movie": (
                "favorite movie",
                "favourite movie",
            ),

            "favorite_color": (
                "favorite color",
                "favourite color",
                "favourite colour",
            ),

            "favorite_game": (
                "favorite game",
                "favourite game",
            ),

            "favorite_food": (
                "favorite food",
                "favourite food",
            ),
        }

        for subject, phrases in groups.items():
            if any(
                phrase in q
                for phrase in phrases
            ):
                aliases.add(
                    subject
                )

        return aliases

    def _key_subject_aliases(
        self,
        key: str
    ) -> set:
        """Map common memory-key shapes to stable subjects."""

        k = self._normalize(
            key
        )

        aliases = set()

        if k in {
            "name",
            "user name",
            "full name",
        }:
            aliases.add(
                "name"
            )

        if any(
            token in k
            for token in (
                "degree",
                "education",
                "education level",
                "current year",
            )
        ):
            aliases.add(
                "education"
            )

        if any(
            token in k
            for token in (
                "postgraduate",
                "study destination",
                "preferred country",
                "planned postgraduate location",
                "postgraduate location",
            )
        ):
            aliases.add(
                "postgraduate"
            )

        if (
            "goal" in k
            or "plan" in k
            or "future" in k
        ):
            aliases.add(
                "goal"
            )

        if (
            "preference" in k
            or "priority" in k
        ):
            aliases.add(
                "preference"
            )

        for subject in (
            "movie",
            "color",
            "game",
            "food",
        ):
            if (
                "favorite " + subject in k
                or "favourite " + subject in k
            ):
                aliases.add(
                    "favorite_" + subject
                )

        return aliases

    def _subject_alias(
        self,
        word: str
    ) -> str:
        return {
            "favourite": "favorite",
            "colour": "color",
            "masters": "master",
        }.get(
            word,
            word,
        )

    # =========================================================
    # QUERY CLASSIFICATION HELPERS
    # =========================================================

    def _is_broad_memory_query(
        self,
        query: str
    ) -> bool:
        return self._contains_any(
            query,
            (
                "what do you remember about me",
                "what do you know about me",
                "what have you remembered about me",
                "what have you learned about me",
                "tell me what you remember about me",
                "tell me what you know about me",
                "show me what you remember about me",
                "show me what you know about me",
                "what information do you remember about me",
                "what information do you know about me",
            ),
        )

    def _is_sensitive_query(
        self,
        query: str
    ) -> bool:
        """Second-layer protection for identity/security-sensitive requests."""

        normalized = self._normalize(
            query
        )

        patterns = (
            r"\baadhaar\b",
            r"\baadhar\b",
            r"\bpan\s*(?:number|card)?\b",
            r"\bpassport\s*(?:number|id)?\b",
            r"\botp\b",
            r"\bone[- ]time password\b",
            r"\bpin\b",
            r"\bpassword\b",
            r"\bsecurity code\b",
            r"\bverification code\b",
            r"\bcredit card\b",
            r"\bdebit card\b",
            r"\bbank account\b",
            r"\baccount number\b",
        )

        return any(
            re.search(
                pattern,
                normalized,
            )
            for pattern in patterns
        )

    def _is_sensitive_memory(
        self,
        memory: Dict[str, Any]
    ) -> bool:
        """Reject sensitive records even if they slipped into route context."""

        key = self._normalize(
            str(
                memory.get("key") or ""
            )
        )

        value = self._normalize(
            str(
                memory.get("value") or ""
            )
        )

        sensitive_terms = (
            "aadhaar",
            "aadhar",
            "pan number",
            "pan card",
            "passport",
            "otp",
            "one time password",
            "pin",
            "password",
            "security code",
            "verification code",
            "credit card",
            "debit card",
            "bank account",
            "account number",
        )

        return any(
            term in key
            or term in value
            for term in sensitive_terms
        )

    # =========================================================
    # GENERAL HELPERS
    # =========================================================

    def _generic_memory_words(
        self
    ) -> set:
        """
        Words that describe the relationship to a memory rather
        than the actual subject of the memory.
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

        normalized = self._normalize(
            text
        )

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

        # Exact key first.
        for preferred in preferred_keys:
            for item in memories:
                if item["key"] == preferred:
                    return item["value"]

        # Canonical subject match.
        preferred_canonical = {
            self._canonical_memory_subject(
                preferred
            )
            for preferred in preferred_keys
        }

        for item in memories:
            item_canonical = (
                self._canonical_memory_subject(
                    item["key"]
                )
            )

            if item_canonical in preferred_canonical:
                return item["value"]

        # Partial key fallback.
        for preferred in preferred_keys:
            for item in memories:
                if (
                    preferred in item["key"]
                    or item["key"] in preferred
                ):
                    return item["value"]

        return None

    def _readable_memory_key(
        self,
        key: str
    ) -> str:
        """Convert an internal memory key to human-readable wording."""

        canonical = self._canonical_memory_subject(
            key
        )

        readable = (
            canonical
            .replace("favorite_", "favorite ")
            .replace("favourite_", "favorite ")
            .replace("_", " ")
        )

        return readable.strip()

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

        text = str(
            text or ""
        ).lower()

        text = text.replace(
            "_",
            " ",
        )

        text = text.replace(
            "favourite",
            "favorite",
        )

        text = text.replace(
            "colour",
            "color",
        )

        text = re.sub(
            r"[^a-z0-9\s]",
            " ",
            text,
        )

        return re.sub(
            r"\s+",
            " ",
            text,
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
                normalized,
            )

            if not match:
                continue

            subject = match.group(
                1
            ).strip()

            subject = re.sub(
                r"\b(favorite|favourite)\b",
                "",
                subject,
            )

            subject = re.sub(
                r"\s+",
                " ",
                subject,
            ).strip()

            if subject:
                return subject

        return None