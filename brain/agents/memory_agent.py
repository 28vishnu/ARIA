from typing import Any, Dict, List

from brain.agents.base_agent import BaseAgent, AgentResponse


class MemoryAgent(BaseAgent):
    """
    Personal context and long-term memory retrieval agent.

    This agent is grounded: it reports only memories that the configured memory
    backend actually returned. It never invents user facts and never claims a
    memory was stored when no backend is available.
    """

    name = "memory"
    aliases = ("memory_engine", "profile")

    description = "Personal context and long-term memory operations agent."
    version = "2.0.0"
    priority = 100
    timeout_seconds = 20.0
    max_retries = 0

    async def can_handle(
        self,
        query: str,
        context: Dict[str, Any],
    ) -> float:

        q = str(query or "").lower()

        keywords = [
            "remember",
            "what is my",
            "do you recall",
            "my preferences",
            "save this",
            "store this",
            "my background",
            "my name",
            "forget",
        ]

        if any(phrase in q for phrase in keywords):
            return 0.98

        return 0.0

    async def execute(
        self,
        query: str,
        context: Dict[str, Any],
    ) -> AgentResponse:

        backend, backend_name = self._memory_backend(context)

        if backend is None:
            return AgentResponse(
                success=False,
                confidence=0.0,
                agent=self.name,
                data={},
                error=(
                    "Long-term memory is unavailable because no memory "
                    "backend is configured. I cannot confirm or recall "
                    "stored personal facts."
                ),
            )

        try:
            memories = await self._retrieve(backend, query)
        except Exception as exc:
            return AgentResponse(
                success=False,
                confidence=0.0,
                agent=self.name,
                data={},
                error=f"Memory retrieval failed: {type(exc).__name__}: {exc}",
            )

        items = self._normalize_memories(memories)

        if not items:
            return AgentResponse(
                success=True,
                confidence=0.75,
                agent=self.name,
                data={
                    "response": (
                        "I don't have a stored memory matching that request."
                    ),
                    "memories": [],
                    "backend": backend_name,
                },
                metadata={"grounded": True, "memory_count": 0},
            )

        lines = ["Stored memory:"]
        for item in items[:20]:
            key = str(item.get("key") or "fact").replace("_", " ")
            value = str(item.get("value") or "").strip()
            if value:
                lines.append(f"- {key}: {value}")

        return AgentResponse(
            success=True,
            confidence=0.9,
            agent=self.name,
            data={
                "response": "\n".join(lines),
                "memories": items,
                "backend": backend_name,
            },
            metadata={"grounded": True, "memory_count": len(items)},
        )

    def _memory_backend(self, context: Dict[str, Any]):
        for key in ("memory_engine", "memory_router"):
            candidate = context.get(key)
            if candidate is not None and (
                hasattr(candidate, "retrieve")
                or hasattr(candidate, "recall")
            ):
                return candidate, key

        registry = self._registry(context)
        if registry is not None:
            for key in ("memory_engine", "memory_router"):
                try:
                    if registry.has(key):
                        candidate = registry.get(key)
                        if candidate is not None and (
                            hasattr(candidate, "retrieve")
                            or hasattr(candidate, "recall")
                        ):
                            return candidate, key
                except Exception:
                    continue

        return None, ""

    @staticmethod
    async def _retrieve(backend: Any, query: str):
        if hasattr(backend, "retrieve"):
            try:
                return await backend.retrieve(query=query)
            except TypeError:
                return await backend.retrieve(query)
        return await backend.recall(query)

    @staticmethod
    def _normalize_memories(memories: Any) -> List[Dict[str, Any]]:
        if memories is None:
            return []
        if isinstance(memories, dict):
            for key in ("memories", "results", "items", "data"):
                value = memories.get(key)
                if isinstance(value, list):
                    memories = value
                    break
            else:
                if "key" in memories and "value" in memories:
                    memories = [memories]
                else:
                    memories = list(memories.values())
        if not isinstance(memories, (list, tuple)):
            return []

        items = []
        for memory in memories:
            if isinstance(memory, dict):
                key = memory.get("key") or memory.get("name") or memory.get("type")
                value = memory.get("value") or memory.get("content") or memory.get("text")
                if key and value is not None:
                    items.append(
                        {
                            "key": str(key),
                            "value": str(value),
                            "category": memory.get("category"),
                        }
                    )
            elif hasattr(memory, "key") and hasattr(memory, "value"):
                items.append(
                    {
                        "key": str(getattr(memory, "key")),
                        "value": str(getattr(memory, "value")),
                    }
                )
        return items
