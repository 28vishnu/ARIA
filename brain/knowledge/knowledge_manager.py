class KnowledgeManager:

    def __init__(
        self,
        document_ai,
        memory_engine,
        state_manager,
    ):
        self.document_ai = document_ai
        self.memory_engine = memory_engine
        self.state_manager = state_manager

    async def answer(
        self,
        session_id,
        question,
    ):
        state = self.state_manager.get_state(session_id)

        # If a document is active, answer from it first.
        if state.get("active_document"):
            answer = await self.document_ai.answer_question(
                session_id=session_id,
                question=question,
                state=state,
            )

            if answer:
                return answer

        # Otherwise search memory.
        memories = await self.memory_engine.retrieve(question)

        if memories:
            return memories

        return None