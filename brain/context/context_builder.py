from typing import Dict, Any, Optional


class ContextBuilder:
    """
    Builds ARIA's unified working context.

    This is not a response generator.

    Its purpose is to organize everything ARIA currently knows about
    the request so reasoning, memory, tools, documents and language
    generation all operate from the same understanding.
    """

    def __init__(
        self,
        state_manager=None,
        world_model=None,
        memory_router=None,
        knowledge_graph=None,
        conversation_manager=None,
        working_memory=None,
    ):
        self.state_manager = state_manager
        self.world_model = world_model
        self.memory_router = memory_router
        self.knowledge_graph = knowledge_graph
        self.conversation_manager = conversation_manager
        self.working_memory = working_memory

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

        # -----------------------------------------------------
        # Base context
        # -----------------------------------------------------

        ctx = dict(base_context or {})

        working_topic = None
        working_goal = None
        working_entities = []
        working_document = None
        last_question = None
        last_answer = None

        if self.working_memory:
            working_topic = self.working_memory.get_topic()
            working_goal = self.working_memory.get_goal()
            working_entities = self.working_memory.get_entities()
            working_document = self.working_memory.get_document()
            last_question = self.working_memory.last_question()
            last_answer = self.working_memory.last_answer()

        # -----------------------------------------------------
        # Canonical cognitive inputs
        # -----------------------------------------------------

        if intent is not None:
            intent_query = getattr(
                intent,
                "original_query",
                "",
            )

            if not query:
                query = intent_query

        clean_query = str(
            query or ""
        ).strip()

        memory_items = (
            memory
            if isinstance(memory, list)
            else []
        )

        state_data = (
            state
            if isinstance(state, dict)
            else {}
        )

        if conversation_history is not None:
            if isinstance(
                conversation_history,
                list,
            ):
                state_data = dict(state_data)

                state_data[
                    "conversation_history"
                ] = conversation_history

        conversation_context = {}

        if self.conversation_manager:
            try:
                conversation_context = self.conversation_manager.get_context(session_id)
            except Exception:
                conversation_context = {}

        # -----------------------------------------------------
        # Conversation state
        # -----------------------------------------------------

        previous_query = state_data.get("last_query")

        last_assistant_response = state_data.get(
            "last_assistant_response"
        )

        conversation_history = state_data.get(
            "conversation_history",
            []
        )

        if not isinstance(conversation_history, list):
            conversation_history = []

        # Keep cognitive context bounded even if state contains more.
        recent_conversation = conversation_history[-8:]

        active_document = (
            state_data.get("active_document")
            or state_data.get("current_document")
        )

        last_document_question = state_data.get(
            "last_document_question"
        )

        # -----------------------------------------------------
        # Basic conversational characteristics
        # -----------------------------------------------------

        words = clean_query.split()

        is_short_query = len(words) <= 6

        normalized = clean_query.lower()

        # -----------------------------------------------------
        # Conversation continuity signals
        #
        # These are linguistic hints, not hard routing rules.
        # ReasoningEngine decides how much they matter.
        # -----------------------------------------------------

        continuation_phrases = {
            "continue",
            "continue please",
            "go on",
            "go ahead",
            "next",
            "carry on",
            "keep going",
            "tell me more",
            "more",
            "explain further",
            "continue that",
            "explain more",
            "what about that",
            "what about it",
            "and?",
            "then?",
        }

        acknowledgement_phrases = {
            "yes",
            "yeah",
            "yep",
            "yup",
            "ok",
            "okay",
            "sure",
            "right",
            "correct",
            "exactly",
            "alright",
            "got it",
            "i see",
            "makes sense",
        }

        negative_acknowledgements = {
            "no",
            "nope",
            "not really",
            "wrong",
            "incorrect",
        }

        selection_phrases = {
            "first one",
            "second one",
            "third one",
            "last one",
            "the first",
            "the second",
            "the third",
            "the last",
        }

        is_continuation = normalized in continuation_phrases

        is_acknowledgement = (
            normalized in acknowledgement_phrases
        )

        is_negative_acknowledgement = (
            normalized in negative_acknowledgements
        )

        is_selection = (
            normalized in selection_phrases
        )

        # -----------------------------------------------------
        # Follow-up detection
        # -----------------------------------------------------

        follow_up_starters = (
            "what about ",
            "how about ",
            "and ",
            "then ",
            "why ",
            "how ",
            "which ",
            "what ",
            "where ",
            "when ",
        )

        contextual_references = (
            "it",
            "that",
            "this",
            "those",
            "these",
            "them",
            "there",
            "same",
        )

        has_contextual_reference = any(
            word in normalized.split()
            for word in contextual_references
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
                    and normalized.startswith(
                        follow_up_starters
                    )
                )
            )
        )

        # -----------------------------------------------------
        # Memory availability
        # -----------------------------------------------------

        has_relevant_memory = bool(memory_items)

        # -----------------------------------------------------
        # Document awareness
        # -----------------------------------------------------

        document_active = bool(active_document or working_document)

        # -----------------------------------------------------
        # Response-depth hint
        # -----------------------------------------------------

        detailed_request_markers = (
            "explain in detail",
            "explain deeply",
            "in detail",
            "step by step",
            "give me steps",
            "teach me",
            "analyse",
            "analyze",
            "compare",
            "full explanation",
            "complete explanation",
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

        # -----------------------------------------------------
        # Unified context
        # -----------------------------------------------------

        ctx.update({
            "context_version": 2,
            "query": clean_query,
            "session_id": session_id,
            "user_id": user_id,
            "intent": {
                "type": getattr(
                    intent,
                    "intent_type",
                    None,
                ),
                "confidence": getattr(
                    intent,
                    "confidence",
                    None,
                ),
                "entities": getattr(
                    intent,
                    "entities",
                    [],
                ),
                "requires_memory": getattr(
                    intent,
                    "requires_memory",
                    False,
                ),
                "requires_documents": getattr(
                    intent,
                    "requires_documents",
                    False,
                ),
                "requires_web": getattr(
                    intent,
                    "requires_web",
                    False,
                ),
                "requires_reasoning": getattr(
                    intent,
                    "requires_reasoning",
                    False,
                ),
                "metadata": getattr(
                    intent,
                    "metadata",
                    {},
                ),
            },
            "user_identity": {
                "user_id": user_id,
                "name": conversation_context.get("user_name"),
            },

            # Persistent knowledge
            "memory": memory_items,

            # Temporary conversation state
            "state": state_data,

            # Working memory state
            "working_memory": {
                "topic": working_topic,
                "goal": working_goal,
                "entities": working_entities,
                "document": working_document,
                "last_question": last_question,
                "last_answer": last_answer,
            },

            # Active context situation object
            "active_context": {
                "topic": (
                    conversation_context.get("topic")
                    or conversation_context.get("current_topic")
                    or working_topic
                ),
                "goal": working_goal,
                "entities": working_entities,
                "document": active_document or working_document,
            },

            # Conversation understanding
            "conversation": {
                "previous_query": previous_query,
                "current_query": clean_query,
                "last_assistant_response": last_assistant_response,
                "history": recent_conversation,

                "topic": (
                    conversation_context.get("topic")
                    or conversation_context.get("current_topic")
                    or working_topic
                ),
                "previous_topic": conversation_context.get(
                    "previous_topic"
                ),

                "entities": conversation_context.get(
                    "entities",
                    [],
                ),

                "active_entities": conversation_context.get(
                    "active_entities",
                    conversation_context.get(
                        "entities",
                        [],
                    ),
                ),

                "compared_entities": conversation_context.get(
                    "compared_entities",
                    conversation_context.get(
                        "last_compared_entities",
                        [],
                    ),
                ),

                "active_comparison": conversation_context.get(
                    "active_comparison",
                    False,
                ),

                "last_question": last_question,
                "last_answer": last_answer,
                "user_name": conversation_context.get(
                    "user_name"
                ),
                "last_result": conversation_context.get(
                    "last_result"
                ),
                "last_result_source": conversation_context.get(
                    "last_result_source"
                ),
                "last_result_operation": conversation_context.get(
                    "last_result_operation"
                ),
                "last_subject": conversation_context.get(
                    "last_subject"
                ),

                "pending_reference": conversation_context.get("pending_reference"),
                "last_compared_entities": conversation_context.get(
                    "last_compared_entities",
                    [],
                ),

                "follow_up": looks_like_follow_up,
                "active_document": active_document,
                "last_plan": state_data.get("last_plan"),
                "last_tool": state_data.get("last_tool"),
                "user_goal": state_data.get("current_goal"),

                "is_short_query": is_short_query,
                "is_continuation": is_continuation,
                "is_acknowledgement": is_acknowledgement,
                "is_negative_acknowledgement": is_negative_acknowledgement,
                "is_selection": is_selection,

                "looks_like_follow_up": looks_like_follow_up,
                "has_contextual_reference": has_contextual_reference,
            },

            # Knowledge availability
            "knowledge": {
                "has_relevant_memory": has_relevant_memory,
                "memory_count": len(memory_items),
                "requires_memory": bool(
                    getattr(
                        intent,
                        "requires_memory",
                        False,
                    )
                ),
                "requires_web": bool(
                    getattr(
                        intent,
                        "requires_web",
                        False,
                    )
                ),
                "requires_documents": bool(
                    getattr(
                        intent,
                        "requires_documents",
                        False,
                    )
                ),
                "requires_reasoning": bool(
                    getattr(
                        intent,
                        "requires_reasoning",
                        False,
                    )
                ),
            },

            "capabilities": {
                "conversation": True,
                "memory": bool(self.memory_router or memory_items),
                "knowledge_graph": bool(self.knowledge_graph),
                "world_model": bool(self.world_model),
                "working_memory": bool(self.working_memory),
                "documents": document_active,
            },

            # Document state
            "document": {
                "active": document_active,
                "name": active_document or working_document,
                "last_question": last_document_question,
            },

            # Presentation guidance.
            # This is a hint for later reasoning, not a hard rule.
            "response": {
                "depth": response_depth,
            },
        })

        return ctx
