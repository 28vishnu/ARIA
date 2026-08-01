from typing import Optional, Dict, Any


class KnowledgeManager:

    def __init__(
        self,
        document_ai,
        memory_engine,
        state_manager,
        knowledge_database=None,
        knowledge_graph=None,
        learning_engine=None,
    ):

        self.document_ai = document_ai
        self.memory_engine = memory_engine
        self.state_manager = state_manager

        self.knowledge_database = knowledge_database
        self.knowledge_graph = knowledge_graph
        self.learning_engine = learning_engine

    ###########################################################
    # Main Search Pipeline
    ###########################################################

    async def answer(
        self,
        session_id,
        question,
    ):

        state = self.state_manager.get_state(session_id)

        #######################################################
        # 1 Active document
        #######################################################

        if state.get("active_document"):

            answer = await self.document_ai.answer_question(
                session_id=session_id,
                question=question,
                state=state,
            )

            if answer:
                return answer

        #######################################################
        # 2 Knowledge Database
        #######################################################

        if self.knowledge_database:

            knowledge = await self.knowledge_database.search(
                question
            )

            if knowledge:
                return knowledge

        #######################################################
        # 3 Personal Memory
        #######################################################

        memories = await self.memory_engine.get_relevant_memories(
            question
        )

        if memories:

            return "\n".join(
                m.get("content", str(m))
                for m in memories
            )

        #######################################################
        # 4 Knowledge Graph
        #######################################################

        if self.knowledge_graph:

            graph = await self.knowledge_graph.search(
                question
            )

            if graph:
                return graph

        #######################################################
        # 5 Nothing Found
        #######################################################

        return None

    ###########################################################
    # Learn New Knowledge
    ###########################################################

    async def learn(
        self,
        text,
        source="conversation"
    ):

        if self.learning_engine:

            await self.learning_engine.learn(
                text=text,
                source=source,
            )

    ###########################################################
    # Store Structured Fact
    ###########################################################

    async def remember_fact(
        self,
        subject,
        relation,
        value
    ):

        if self.knowledge_graph:

            await self.knowledge_graph.add_fact(
                subject,
                relation,
                value
            )

    ###########################################################
    # Save Knowledge
    ###########################################################

    async def save_knowledge(
        self,
        title,
        content,
        source="conversation"
    ):

        if self.knowledge_database:

            await self.knowledge_database.store(
                title=title,
                content=content,
                source=source
            )