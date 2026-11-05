"""Step 2 regression tests for durable ARIA/JARVIS memory APIs."""
import pytest

from brain.memory.jarvis_memory_system import JarvisMemorySystem


class FakeDurableMemory:
    """Shared backing store simulates a durable backend across gateway restarts."""
    def __init__(self, store=None):
        self.store = store if store is not None else {}

    async def store_profile(self, payload):
        self.store.setdefault("profile", {}).update(payload)

    async def get_profile(self):
        return dict(self.store.get("profile", {}))

    async def process_and_store(self, text):
        self.store.setdefault("memories", []).append(text)
        return {"success": True, "stored": text}

    async def get_relevant_memories(self, query, limit=10):
        values = self.store.get("memories", [])
        terms = [term.lower() for term in query.split() if len(term) > 2]
        ranked = [value for value in values if any(term in value.lower() for term in terms)]
        return [{"text": value} for value in ranked[:limit]]

    async def delete_memory(self, query):
        values = self.store.get("memories", [])
        before = len(values)
        self.store["memories"] = [value for value in values if query.lower() not in value.lower()]
        return len(self.store["memories"]) < before


@pytest.mark.asyncio
async def test_profile_memory_survives_gateway_recreation():
    backing_store = {}
    first = JarvisMemorySystem(memory_engine=FakeDurableMemory(backing_store))

    result = await first.remember(
        {"category": "profile", "key": "preferred_name", "value": "Sir"},
        explicit=True,
    )
    assert result["success"] is True

    # Recreate the gateway, as happens after an application restart.
    second = JarvisMemorySystem(memory_engine=FakeDurableMemory(backing_store))
    assert await second.get_profile() == {"preferred_name": "Sir"}


@pytest.mark.asyncio
async def test_ordinary_memory_can_be_recalled_after_gateway_recreation():
    backing_store = {}
    first = JarvisMemorySystem(memory_engine=FakeDurableMemory(backing_store))
    result = await first.remember("Project ARIA uses Python and MongoDB", explicit=True)
    assert result["success"] is True

    second = JarvisMemorySystem(memory_engine=FakeDurableMemory(backing_store))
    result = await second.recall("ARIA Python")
    assert result["personal_memory"]
    assert "Project ARIA" in result["personal_memory"][0]["text"]


@pytest.mark.asyncio
async def test_forget_delegates_to_durable_owner_and_reports_outcome():
    backing_store = {"memories": ["User prefers concise answers", "Project ARIA uses Python"]}
    system = JarvisMemorySystem(memory_engine=FakeDurableMemory(backing_store))

    result = await system.forget("concise answers")
    assert result["success"] is True
    assert backing_store["memories"] == ["Project ARIA uses Python"]

    missing = await system.forget("not stored")
    assert missing["success"] is False
    assert missing["reason"] == "not_found_or_blocked"


@pytest.mark.asyncio
async def test_forget_rejects_empty_query_without_touching_backend():
    system = JarvisMemorySystem(memory_engine=FakeDurableMemory({"memories": ["keep"]}))
    result = await system.forget("   ")
    assert result == {"success": False, "reason": "empty_query"}


@pytest.mark.asyncio
async def test_missing_durable_backend_is_reported_not_faked():
    system = JarvisMemorySystem()
    assert await system.get_profile() == {}
    result = await system.forget("anything")
    assert result["success"] is False
    assert result["reason"] == "durable_memory_unavailable"
