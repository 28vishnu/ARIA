from typing import Dict, Any, Optional


class ContextBuilder:
    """
    Builds ARIA's unified working context.

    This is not a response generator.

    Its purpose is to organize everything ARIA currently knows about
    the request so reasoning, memory, tools, documents and language
    generation all operate from the same understanding.
    """

    async def build(
        self,
        query: str,
        session_id: str,
        user_id: str,
        base_context: Optional[Dict[str, Any]] = None,
        memory=None,
        state=None,
    ) -> Dict[str, Any]:

        # -----------------------------------------------------
        # Base context
        # -----------------------------------------------------

        ctx = dict(base_context or {})

        clean_query = str(query or "").strip()

        memory_items = memory if isinstance(memory, list) else []
        state_data = state if isinstance(state, dict) else {}

        # -----------------------------------------------------
        # Conversation state
        # -----------------------------------------------------

        previous_query = state_data.get("last_query")

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
            "go on",
            "next",
            "tell me more",
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

        document_active = bool(active_document)

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
            "query": clean_query,
            "session_id": session_id,
            "user_id": user_id,

            # Persistent knowledge
            "memory": memory_items,

            # Temporary conversation state
            "state": state_data,

            # Conversation understanding
            "conversation": {
                "previous_query": previous_query,
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
            },

            # Document state
            "document": {
                "active": document_active,
                "name": active_document,
                "last_question": last_document_question,
            },

            # Presentation guidance.
            # This is a hint for later reasoning, not a hard rule.
            "response": {
                "depth": response_depth,
            },
        })

        return ctx
