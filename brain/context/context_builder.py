from typing import Dict, Any, Optional, List
import copy
import re
import uuid
import time
import logging

logger = logging.getLogger("aria")


class ContextBuilder:
    """
    Canonical, side-effect-free context assembly layer for ARIA.

    ContextBuilder collects request, conversation, memory, state, intent,
    working-memory and orchestration signals into one bounded context object.

    It does NOT:
      - call an LLM
      - execute tools/actions
      - mutate persistent memory
      - perform planning
      - make the final routing decision

    Those responsibilities remain with the appropriate orchestration layers.
    """

    CONTEXT_VERSION = 3
    MAX_HISTORY = 8
    MAX_ENTITIES = 32
    MAX_STRING = 4000

    def __init__(
        self,
        state_manager=None,
        world_model=None,
        memory_router=None,
        knowledge_graph=None,
        conversation_manager=None,
        working_memory=None,
        tool_manager=None,
        agent_coordinator=None,
        planner=None,
        executor=None,
        goal_manager=None,
        reasoning_engine=None,
    ):
        self.state_manager = state_manager
        self.world_model = world_model
        self.memory_router = memory_router
        self.knowledge_graph = knowledge_graph
        self.conversation_manager = conversation_manager
        self.working_memory = working_memory

        # Phase 11 orchestration awareness.
        # These references are observational only.
        self.tool_manager = tool_manager
        self.agent_coordinator = agent_coordinator
        self.planner = planner
        self.executor = executor
        self.goal_manager = goal_manager
        self.reasoning_engine = reasoning_engine

    # ------------------------------------------------------------------
    # Normalization helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_dict(value: Any) -> Dict[str, Any]:
        return dict(value) if isinstance(value, dict) else {}

    @classmethod
    def _safe_text(cls, value: Any, default: str = "") -> str:
        try:
            text = str(value if value is not None else default).strip()
        except Exception:
            return default
        return text[: cls.MAX_STRING]

    @classmethod
    def _safe_list(cls, value: Any) -> List[Any]:
        if isinstance(value, list):
            return value
        if value is None:
            return []
        return [value]

    @classmethod
    def _clean_entities(cls, values: Any) -> List[str]:
        result = []
        seen = set()

        for value in cls._safe_list(values):
            text = re.sub(r"\s+", " ", cls._safe_text(value)).strip(" .,!?:;")
            if not text:
                continue

            normalized = text.lower()
            if normalized in {
                "context",
                "previous context",
                "current context",
                "active context",
                "unknown",
                "none",
            }:
                continue

            if normalized.endswith(" context"):
                continue

            if normalized in seen:
                continue

            seen.add(normalized)
            result.append(text)

            if len(result) >= cls.MAX_ENTITIES:
                break

        return result

    @staticmethod
    def _intent_value(intent: Any, key: str, default: Any = None) -> Any:
        if intent is None:
            return default

        if isinstance(intent, dict):
            return intent.get(key, default)

        return getattr(intent, key, default)

    def _normalize_intent(self, intent: Any) -> Dict[str, Any]:
        intent_type = self._intent_value(intent, "intent_type")
        if intent_type is None:
            intent_type = self._intent_value(intent, "type")

        confidence = self._intent_value(intent, "confidence", 0.0)
        try:
            confidence = float(confidence or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0

        return {
            "type": self._safe_text(intent_type) or None,
            "confidence": max(0.0, min(1.0, confidence)),
            "entities": self._clean_entities(
                self._intent_value(intent, "entities", [])
            ),
            "requires_memory": bool(
                self._intent_value(intent, "requires_memory", False)
            ),
            "requires_documents": bool(
                self._intent_value(intent, "requires_documents", False)
            ),
            "requires_web": bool(
                self._intent_value(intent, "requires_web", False)
            ),
            "requires_reasoning": bool(
                self._intent_value(intent, "requires_reasoning", False)
            ),
            "requires_tools": bool(
                self._intent_value(intent, "requires_tools", False)
            ),
            "requires_planning": bool(
                self._intent_value(intent, "requires_planning", False)
            ),
            "metadata": self._safe_dict(
                self._intent_value(intent, "metadata", {})
            ),
        }

    @classmethod
    def _bounded_history(cls, history: Any) -> List[Any]:
        if not isinstance(history, list):
            return []

        # Copy entries so later pipeline mutations cannot mutate source state.
        bounded = []
        for item in history[-cls.MAX_HISTORY :]:
            if isinstance(item, dict):
                bounded.append(copy.deepcopy(item))
            else:
                bounded.append(cls._safe_text(item))
        return bounded

    def _get_working_memory(self) -> Dict[str, Any]:
        if not self.working_memory:
            return {
                "topic": None,
                "goal": None,
                "entities": [],
                "document": None,
                "last_question": None,
                "last_answer": None,
            }

        def call(method, default=None):
            try:
                fn = getattr(self.working_memory, method, None)
                return fn() if callable(fn) else default
            except Exception:
                logger.debug(
                    "[ContextBuilder] Working-memory %s unavailable",
                    method,
                    exc_info=True,
                )
                return default

        return {
            "topic": self._safe_text(call("get_topic")) or None,
            "goal": self._safe_text(call("get_goal")) or None,
            "entities": self._clean_entities(call("get_entities")),
            "document": call("get_document"),
            "last_question": self._safe_text(call("last_question")) or None,
            "last_answer": self._safe_text(call("last_answer")) or None,
        }

    def _get_conversation_context(self, session_id: str) -> Dict[str, Any]:
        if not self.conversation_manager:
            return {}

        try:
            getter = getattr(self.conversation_manager, "get_context", None)
            if not callable(getter):
                return {}
            value = getter(session_id)
            return self._safe_dict(value)
        except Exception:
            logger.debug(
                "[ContextBuilder] Conversation context unavailable",
                exc_info=True,
            )
            return {}

    # ------------------------------------------------------------------
    # Main context construction
    # ------------------------------------------------------------------

    async def build(
        self,
        query: str = "",
        session_id: str = "",
        user_id: str = "",
        base_context: Optional[Dict[str, Any]] = None,
        memory=None,
        state=None,
        intent=None,
        conversation_history=None,
    ) -> Dict[str, Any]:

        # Never mutate caller-owned nested structures.
        ctx = copy.deepcopy(base_context) if isinstance(base_context, dict) else {}

        state_data = copy.deepcopy(state) if isinstance(state, dict) else {}

        normalized_intent = self._normalize_intent(intent)

        intent_query = self._intent_value(intent, "original_query", "")
        clean_query = self._safe_text(query or intent_query)

        if not clean_query:
            clean_query = self._safe_text(ctx.get("query"))

        resolved_query = self._safe_text(
            ctx.get("resolved_query") or clean_query
        )

        memory_items = (
            copy.deepcopy(memory)
            if isinstance(memory, list)
            else []
        )

        working = self._get_working_memory()
        conversation_context = self._get_conversation_context(session_id)

        # --------------------------------------------------------------
        # Conversation history
        # --------------------------------------------------------------

        stored_history = state_data.get("conversation_history", [])
        if not isinstance(stored_history, list):
            stored_history = []

        if isinstance(conversation_history, list):
            effective_history = conversation_history
        else:
            effective_history = stored_history

        recent_conversation = self._bounded_history(effective_history)

        previous_query = self._safe_text(
            state_data.get("last_query")
            or conversation_context.get("previous_query")
        ) or None

        last_assistant_response = self._safe_text(
            state_data.get("last_assistant_response")
            or conversation_context.get("last_assistant_response")
        ) or None

        active_document = (
            state_data.get("active_document")
            or state_data.get("current_document")
            or conversation_context.get("active_document")
            or working.get("document")
        )

        last_document_question = self._safe_text(
            state_data.get("last_document_question")
        ) or None

        # --------------------------------------------------------------
        # Conversational signals
        # --------------------------------------------------------------

        words = clean_query.split()
        is_short_query = len(words) <= 6
        normalized = clean_query.lower()

        continuation_phrases = {
            "continue", "continue please", "go on", "go ahead", "next",
            "carry on", "keep going", "tell me more", "more",
            "explain further", "continue that", "explain more",
            "what about that", "what about it", "and?", "then?",
        }

        acknowledgement_phrases = {
            "yes", "yeah", "yep", "yup", "ok", "okay", "sure", "right",
            "correct", "exactly", "alright", "got it", "i see",
            "makes sense",
        }

        negative_acknowledgements = {
            "no", "nope", "not really", "wrong", "incorrect",
        }

        selection_phrases = {
            "first one", "second one", "third one", "last one",
            "the first", "the second", "the third", "the last",
        }

        is_continuation = normalized in continuation_phrases
        is_acknowledgement = normalized in acknowledgement_phrases
        is_negative_acknowledgement = normalized in negative_acknowledgements
        is_selection = normalized in selection_phrases

        follow_up_starters = (
            "what about ", "how about ", "and ", "then ", "why ", "how ",
            "which ", "what ", "where ", "when ",
        )

        contextual_references = {
            "it", "that", "this", "those", "these", "them", "there", "same",
        }

        has_contextual_reference = any(
            word in contextual_references
            for word in normalized.split()
        )

        looks_like_follow_up = bool(
            previous_query
            and (
                is_continuation
                or is_acknowledgement
                or is_negative_acknowledgement
                or is_selection
                or has_contextual_reference
                or (
                    is_short_query
                    and normalized.startswith(follow_up_starters)
                )
            )
        )

        # --------------------------------------------------------------
        # Topic/entity state
        # --------------------------------------------------------------

        conversation_topic = (
            conversation_context.get("topic")
            or conversation_context.get("current_topic")
            or working.get("topic")
        )

        previous_topic = conversation_context.get("previous_topic")

        active_entities = self._clean_entities(
            conversation_context.get("active_entities")
            or conversation_context.get("entities")
            or working.get("entities")
            or normalized_intent.get("entities")
        )

        compared_entities = self._clean_entities(
            conversation_context.get("compared_entities")
            or conversation_context.get("last_compared_entities")
        )

        active_comparison = bool(
            conversation_context.get("active_comparison", False)
        )

        # --------------------------------------------------------------
        # Request characteristics
        # --------------------------------------------------------------

        detailed_request_markers = (
            "explain in detail", "explain deeply", "in detail",
            "step by step", "give me steps", "teach me", "analyse",
            "analyze", "compare", "full explanation", "complete explanation",
        )

        wants_detailed_response = any(
            marker in normalized
            for marker in detailed_request_markers
        )

        if wants_detailed_response:
            response_depth = "detailed"
        elif is_short_query:
            response_depth = "concise"
        else:
            response_depth = "normal"

        # --------------------------------------------------------------
        # Capability registry
        #
        # These indicate availability. They do not force execution.
        # --------------------------------------------------------------

        capability_intent = normalized_intent

        capabilities = {
            "conversation": True,
            "memory": bool(
                self.memory_router
                or memory_items
                or capability_intent["requires_memory"]
            ),
            "knowledge_graph": bool(self.knowledge_graph),
            "world_model": bool(self.world_model),
            "working_memory": bool(self.working_memory),
            "documents": bool(
                active_document
                or capability_intent["requires_documents"]
            ),
            "web": bool(
                capability_intent["requires_web"]
                or self.memory_router
            ),
            "reasoning": bool(
                capability_intent["requires_reasoning"]
                or self.reasoning_engine
            ),
            "tools": bool(
                self.tool_manager
                or capability_intent["requires_tools"]
            ),
            "agents": bool(
                self.agent_coordinator
            ),
            "planning": bool(
                self.planner
                or capability_intent["requires_planning"]
            ),
            "execution": bool(self.executor),
            "goals": bool(self.goal_manager),
        }

        # --------------------------------------------------------------
        # Execution / orchestration state
        # --------------------------------------------------------------

        execution_result = ctx.get("execution_result")
        if not isinstance(execution_result, dict):
            execution_result = state_data.get("execution_result")
            if not isinstance(execution_result, dict):
                execution_result = {}

        decision = ctx.get("decision")
        decision_type = (
            type(decision).__name__
            if decision is not None
            else None
        )

        # Keep orchestration metadata descriptive, never executable.
        orchestration = {
            "decision_present": decision is not None,
            "decision_type": decision_type,
            "execution_in_progress": bool(
                state_data.get("execution_in_progress", False)
            ),
            "execution_completed": bool(
                execution_result.get("completed")
            ),
            "execution_failed": bool(
                execution_result.get("failed")
            ),
            "last_plan": copy.deepcopy(
                state_data.get("last_plan")
            ),
            "last_tool": copy.deepcopy(
                state_data.get("last_tool")
            ),
        }

        # --------------------------------------------------------------
        # Unified context
        # --------------------------------------------------------------

        ctx.update({
            "context_version": self.CONTEXT_VERSION,
            "context_id": self._safe_text(
                ctx.get("context_id")
            ) or uuid.uuid4().hex,
            "context_created_at": time.time(),

            "query": clean_query,
            "resolved_query": resolved_query,

            "request": {
                "query": clean_query,
                "resolved_query": resolved_query,
                "session_id": session_id,
                "user_id": user_id,
                "has_query": bool(clean_query),
                "is_short": is_short_query,
                "looks_like_follow_up": looks_like_follow_up,
            },

            "session_id": session_id,
            "user_id": user_id,

            "intent": normalized_intent,

            "intent_requirements": {
                "memory": normalized_intent["requires_memory"],
                "documents": normalized_intent["requires_documents"],
                "web": normalized_intent["requires_web"],
                "reasoning": normalized_intent["requires_reasoning"],
                "tools": normalized_intent["requires_tools"],
                "planning": normalized_intent["requires_planning"],
            },

            "user_identity": {
                "user_id": user_id,
                "name": conversation_context.get("user_name"),
            },

            "memory": memory_items,

            "state": state_data,

            "working_memory": working,

            "active_context": {
                "topic": self._safe_text(conversation_topic) or None,
                "goal": working.get("goal"),
                "entities": active_entities,
                "document": active_document,
            },

            "conversation": {
                "previous_query": previous_query,
                "current_query": clean_query,
                "last_assistant_response": last_assistant_response,
                "history": recent_conversation,

                "topic": self._safe_text(conversation_topic) or None,
                "previous_topic": self._safe_text(previous_topic) or None,

                "entities": active_entities,
                "active_entities": active_entities,
                "compared_entities": compared_entities,
                "active_comparison": active_comparison,

                "last_question": working.get("last_question"),
                "last_answer": working.get("last_answer"),
                "user_name": conversation_context.get("user_name"),

                "last_result": conversation_context.get("last_result"),
                "last_result_source": conversation_context.get(
                    "last_result_source"
                ),
                "last_result_operation": conversation_context.get(
                    "last_result_operation"
                ),
                "last_subject": conversation_context.get("last_subject"),

                "pending_reference": conversation_context.get(
                    "pending_reference"
                ),

                "last_compared_entities": compared_entities,

                "follow_up": looks_like_follow_up,
                "active_document": active_document,
                "last_plan": copy.deepcopy(state_data.get("last_plan")),
                "last_tool": copy.deepcopy(state_data.get("last_tool")),
                "user_goal": state_data.get("current_goal"),

                "is_short_query": is_short_query,
                "is_continuation": is_continuation,
                "is_acknowledgement": is_acknowledgement,
                "is_negative_acknowledgement": is_negative_acknowledgement,
                "is_selection": is_selection,

                "looks_like_follow_up": looks_like_follow_up,
                "has_contextual_reference": has_contextual_reference,
            },

            "knowledge": {
                "has_relevant_memory": bool(memory_items),
                "memory_count": len(memory_items),
                "requires_memory": normalized_intent["requires_memory"],
                "requires_web": normalized_intent["requires_web"],
                "requires_documents": normalized_intent["requires_documents"],
                "requires_reasoning": normalized_intent["requires_reasoning"],
            },

            "capabilities": capabilities,

            "orchestration": orchestration,

            "execution": {
                "result": copy.deepcopy(execution_result),
                "active": orchestration["execution_in_progress"],
                "completed": orchestration["execution_completed"],
                "failed": orchestration["execution_failed"],
            },

            "document": {
                "active": bool(active_document),
                "name": active_document,
                "last_question": last_document_question,
            },

            "response": {
                "depth": response_depth,
                "intent_type": normalized_intent["type"] or "conversation",
                "intent_confidence": normalized_intent["confidence"],
                "requires_reasoning": normalized_intent["requires_reasoning"],
            },
        })

        return ctx
