import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("aria")


class KnowledgeRetriever:
    """
    Unified knowledge retrieval for ARIA.

    Searches multiple knowledge sources so CognitiveCore does not
    need to know whether an answer lives in memory, a document,
    conversation history, or current session context.
    """

    def __init__(
        self,
        memory_engine=None,
        document_ai=None,
        state_manager=None,
    ):
        self.memory_engine = memory_engine
        self.document_ai = document_ai
        self.state_manager = state_manager

    async def retrieve(
        self,
        query: str,
        user_id: str,
        session_id: str,
        context: Optional[Dict[str, Any]] = None,
        limit: int = 10,
    ) -> Dict[str, Any]:

        context = context or {}

        result = {
            "query": query,
            "personal_memories": [],
            "document_knowledge": [],
            "conversation_context": [],
            "active_document": None,
            "has_evidence": False,
        }

        # -----------------------------------------------------
        # 1. PERSONAL / LONG-TERM MEMORY
        # -----------------------------------------------------

        if self.memory_engine is not None:
            try:
                memories = await self.memory_engine.retrieve_relevant(
                    user_id=user_id,
                    query=query,
                    limit=limit,
                )

                if memories:
                    result["personal_memories"] = memories

            except Exception:
                logger.exception(
                    "[KnowledgeRetriever] Memory retrieval failed."
                )

        # -----------------------------------------------------
        # 2. ACTIVE DOCUMENT INFORMATION
        # -----------------------------------------------------

        state = context.get("state", {})

        if not state and self.state_manager is not None:
            try:
                state = self.state_manager.get_state(session_id) or {}
            except Exception:
                logger.exception(
                    "[KnowledgeRetriever] Could not load session state."
                )
                state = {}

        current_document = state.get("current_document")

        if current_document:
            result["active_document"] = current_document

        # -----------------------------------------------------
        # 3. DOCUMENT KNOWLEDGE
        #
        # We will connect the actual DocumentIntelligence
        # retrieval method in the next step.
        # -----------------------------------------------------

        # Intentionally left disconnected for now.
        # Do NOT call answer_question() here because that produces
        # a final answer rather than raw retrieval evidence.

        # -----------------------------------------------------
        # 4. CONVERSATION CONTEXT
        # -----------------------------------------------------

        conversation = (
            context.get("conversation_history")
            or context.get("recent_conversation")
            or []
        )

        if conversation:
            result["conversation_context"] = conversation

        # -----------------------------------------------------
        # 5. EVIDENCE FLAG
        # -----------------------------------------------------

        result["has_evidence"] = bool(
            result["personal_memories"]
            or result["document_knowledge"]
            or result["conversation_context"]
        )

        logger.info(
            "[KnowledgeRetriever] Retrieved knowledge: "
            "memory=%d document=%d conversation=%d active_doc=%s",
            len(result["personal_memories"]),
            len(result["document_knowledge"]),
            len(result["conversation_context"]),
            current_document,
        )

        return result