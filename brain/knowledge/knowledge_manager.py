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

        # 1. Active document
        if state.get("active_document"):

            answer = await self.document_ai.answer_question(
                session_id=session_id,
                question=question,
                state=state,
            )

            if answer:
                return answer

        # 2. Memory
        memories = await self.memory_engine.get_relevant_memories(question)

        if memories:
            return "\n".join(
                m.get("content", str(m))
                for m in memories
            )

        return None
