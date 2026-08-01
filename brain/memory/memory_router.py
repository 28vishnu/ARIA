from typing import Any, Dict, List, Optional

from brain.memory.working_memory import WorkingMemory


class MemoryRouter:
    """
    Central gateway to every memory subsystem.

    Nothing outside the memory package should directly talk to
    MemoryEngine.

    Future sources:
        • Working Memory
        • Personal Memory
        • Document Memory
        • Knowledge Graph
        • World Knowledge
    """

    def __init__(
        self,
        working_memory: WorkingMemory,
        memory_engine=None,
        knowledge_engine=None,
        knowledge_graph=None,
        document_repository=None
    ):
        self.working_memory = working_memory
        self.memory_engine = memory_engine
        self.knowledge_engine = knowledge_engine
        self.knowledge_graph = knowledge_graph
        self.document_repository = document_repository

    # =====================================================
    # Working Memory
    # =====================================================

    def get(self, key: str, default=None):
        return self.working_memory.get(key, default)

    def set(self, key: str, value):
        self.working_memory.set(key, value)

    def delete(self, key):
        self.working_memory.delete(key)

    def clear(self):
        self.working_memory.clear()

    def snapshot(self):
        return self.working_memory.snapshot()

    # =====================================================
    # Long-term Memory
    # =====================================================

    async def remember(
        self,
        user_text: str
    ):
        """
        Learn something from the conversation.
        """

        if self.memory_engine is None:
            return

        return await self.memory_engine.process_and_store(
            user_text
        )

    # =====================================================
    # Memory Recall
    # =====================================================

    async def recall(
        self,
        query: str,
        limit: int = 10
    ) -> List[Dict]:

        if self.memory_engine is None:
            return []

        memories = await self.memory_engine.get_relevant_memories(
            query,
            limit
        )

        return memories

    # =====================================================
    # Unified Recall
    # =====================================================

    async def search_everywhere(
        self,
        query: str,
        limit: int = 10
    ) -> Dict[str, Any]:

        result = {
            "working_memory": None,
            "personal_memory": [],
            "knowledge": None,
            "graph": None
        }

        # Working Memory
        result["working_memory"] = self.snapshot()

        # Personal Memory
        if self.memory_engine:

            result["personal_memory"] = (
                await self.memory_engine.get_relevant_memories(
                    query,
                    limit
                )
            )

        # Knowledge Engine
        if self.knowledge_engine:

            result["knowledge"] = (
                await self.knowledge_engine.search(
                    query
                )
            )

        # Knowledge Graph
        if self.knowledge_graph:

            result["graph"] = (
                await self.knowledge_graph.search(
                    query
                )
            )

        return result

    # =====================================================
    # Answer API
    # =====================================================

    async def answer(self, query: str):

        result = await self.search_everywhere(query)

        if result["personal_memory"]:
            return result["personal_memory"]

        if result["knowledge"]:
            return result["knowledge"]

        if result["graph"]:
            return result["graph"]

        return None

    # =====================================================
    # Store APIs
    # =====================================================

    async def store_document(
        self,
        document
    ):
        if self.document_repository:
            return await self.document_repository.store(document)

    async def store_chat(
        self,
        chat
    ):
        if self.memory_engine:
            return await self.memory_engine.store_chat(chat)

    async def store_profile(
        self,
        profile
    ):
        if self.memory_engine:
            return await self.memory_engine.store_profile(profile)

    async def learn(
        self,
        knowledge
    ):
        if self.knowledge_engine:
            return await self.knowledge_engine.learn(
                knowledge
            )

    async def update_memory(
        self,
        memory_id,
        data
    ):
        if self.memory_engine:
            return await self.memory_engine.update_memory(
                memory_id,
                data
            )

    async def memory_exists(
        self,
        query
    ):
        if self.memory_engine:
            return await self.memory_engine.memory_exists(query)

        return False

    async def knowledge_exists(
        self,
        fact
    ):
        if self.knowledge_engine:
            return await self.knowledge_engine.exists(fact)

        return False

    # =====================================================
    # Delete Memory
    # =====================================================

    async def forget(
        self,
        query: str
    ):

        if self.memory_engine is None:
            return False

        return await self.memory_engine.delete_memory(
            query
        )
