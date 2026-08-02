from typing import Any, Dict, List, Optional
import time

from brain.memory.working_memory import WorkingMemory


class MemoryRouter:
    """
    Central gateway to every memory subsystem.

    Nothing outside the memory package should directly talk to
    MemoryEngine.

    Searches memory only when explicitly requested by the reasoning engine.
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

        # Duplicate guard cache for remember()
        self._last_remembered_text = None
        self._last_remembered_time = 0.0
        self._duplicate_window = 5.0  # seconds

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

        cleaned_text = str(user_text or "").strip()
        if not cleaned_text:
            return

        now = time.monotonic()
        if (
            self._last_remembered_text == cleaned_text
            and (now - self._last_remembered_time) < self._duplicate_window
        ):
            return {"success": False, "reason": "duplicate_suppressed"}

        self._last_remembered_text = cleaned_text
        self._last_remembered_time = now

        return await self.memory_engine.process_and_store(
            user_text
        )

    # =====================================================
    # Memory Recall (Conditional / On-Demand)
    # =====================================================

    async def recall(
        self,
        query: str,
        limit: int = 10,
        force: bool = False,
        reasoning_result: Optional[Any] = None,
    ) -> List[Dict]:
        """
        Recall memories only when requested by the reasoning engine.
        """
        if (
            reasoning_result is not None
            and not getattr(reasoning_result, "requires_memory", True)
        ):
            return []

        if self.memory_engine is None:
            return []

        memories = await self.memory_engine.get_relevant_memories(
            query,
            limit
        )

        if memories is None:
            return []

        filtered = []
        for memory in memories:
            score = memory.get("retrieval_score", 0)
            if score >= 12:
                filtered.append(memory)
        return filtered

    # =====================================================
    # Long-Term Continuous Learning & Reasoning Patterns
    # =====================================================

    async def learn_from_success(self, task_description: str, outcome: Any):
        """
        Store successful task execution patterns for continuous improvement.
        """
        if self.memory_engine and hasattr(self.memory_engine, "process_and_store"):
            await self.memory_engine.process_and_store(f"Successful pattern for {task_description}: {outcome}")

    async def learn_from_failure(self, task_description: str, error: str):
        """
        Store failure patterns to avoid repeating mistakes.
        """
        if self.memory_engine and hasattr(self.memory_engine, "process_and_store"):
            await self.memory_engine.process_and_store(f"Failure pattern to avoid for {task_description}: {error}")

    async def store_reasoning_pattern(self, pattern_key: str, pattern_data: Dict[str, Any]):
        """
        Store generalized reasoning workflow patterns.
        """
        if self.memory_engine and hasattr(self.memory_engine, "process_and_store"):
            await self.memory_engine.process_and_store(f"Reasoning pattern [{pattern_key}]: {pattern_data}")

    async def retrieve_reasoning_pattern(self, pattern_key: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve stored reasoning patterns for optimization.
        """
        if self.memory_engine and hasattr(self.memory_engine, "get_relevant_memories"):
            mems = await self.memory_engine.get_relevant_memories(pattern_key, limit=1)
            if mems:
                return mems[0]
        return None

    async def process_successful_reasoning(self, query: str, reasoning: Any):
        """
        Store reusable reasoning patterns at the end of a successful reasoning cycle.
        """
        await self.store_reasoning_pattern(
            pattern_key=query,
            pattern_data={
                "reasoning": reasoning,
                "success": True,
                "timestamp": time.time(),
            },
        )

    # =====================================================
    # Unified Recall
    # =====================================================

    async def search_everywhere(
        self,
        query: str,
        limit: int = 10,
        reasoning_result: Optional[Any] = None,
    ) -> Dict[str, Any]:

        result = {
            "working_memory": None,
            "personal_memory": [],
            "knowledge": None,
            "graph": None
        }

        # Working Memory
        result["working_memory"] = self.snapshot()

        # Personal Memory (respects reasoning flag)
        should_recall_memory = True
        if reasoning_result is not None:
            should_recall_memory = getattr(reasoning_result, "requires_memory", True)

        if self.memory_engine and should_recall_memory:
            pm = (
                await self.memory_engine.get_relevant_memories(
                    query,
                    limit
                )
            )
            filtered_pm = []
            if pm:
                for memory in pm:
                    score = memory.get("retrieval_score", 0)
                    if score >= 12:
                        filtered_pm.append(memory)
            result["personal_memory"] = filtered_pm

        # Knowledge Engine (respects reasoning flag for documents)
        should_recall_docs = True
        if reasoning_result is not None:
            should_recall_docs = getattr(reasoning_result, "requires_documents", False)

        if self.knowledge_engine and should_recall_docs:
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

    async def answer(self, query: str, reasoning_result: Optional[Any] = None):
        """
        Answer query using search_everywhere with optional reasoning guard.
        """
        result = await self.search_everywhere(query, reasoning_result=reasoning_result)

        if result["personal_memory"]:
            return result["personal_memory"]

        if result["knowledge"]:
            return result["knowledge"]

        if result["graph"]:
            return result["graph"]

        return []

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
