import unittest
from brain.knowledge.retrieval_coordinator import RetrievalCoordinator


class RetrievalCoordinatorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.coordinator = RetrievalCoordinator()

    def test_normalizes_question_and_source_request(self):
        self.assertEqual(
            self.coordinator.normalize_query("Answer using your locally stored knowledge: What is quantum entanglement? And provide the source URL"),
            "quantum entanglement",
        )

    def test_normalizes_simple_factual_question(self):
        self.assertEqual(self.coordinator.normalize_query("What is photosynthesis?"), "photosynthesis")

    async def test_local_hit_skips_online(self):
        calls = {"local": 0, "online": 0}
        async def local(q):
            calls["local"] += 1
            return [{"title": "Photosynthesis", "content": "Photosynthesis converts light energy into chemical energy.", "url": "https://example.org/p"}]
        async def online(q):
            calls["online"] += 1
            return []
        def enough(items, q): return bool(items)
        result = await self.coordinator.retrieve("What is photosynthesis?", local, online, enough)
        self.assertFalse(result.used_online)
        self.assertEqual(calls, {"local": 1, "online": 0})
        self.assertEqual(len(result.evidence), 1)

    async def test_local_miss_uses_normalized_online_query(self):
        seen = []
        async def local(q): return []
        async def online(q):
            seen.append(q)
            return [{"title": "Quantum entanglement", "content": "A physical phenomenon.", "url": "https://example.org/q"}]
        result = await self.coordinator.retrieve("What is quantum entanglement? Please provide the source URL", local, online, lambda items, q: bool(items))
        self.assertEqual(seen, ["quantum entanglement"])
        self.assertTrue(result.used_online)
        self.assertEqual(result.evidence[0]["title"], "Quantum entanglement")

    async def test_weak_local_evidence_is_combined_with_online(self):
        async def local(q): return [{"title": "Random", "content": "Unrelated item", "url": "https://example.org/a"}]
        async def online(q): return [{"title": "Solar System", "content": "The Solar System consists of the Sun and orbiting objects.", "url": "https://example.org/b"}]
        result = await self.coordinator.retrieve("Explain the Solar System", local, online, lambda items, q: bool(items and "Solar System" in items[0].get("title", "")))
        self.assertTrue(result.used_online)
        self.assertEqual(len(result.evidence), 1)

    async def test_online_failure_does_not_raise(self):
        async def local(q): return []
        async def online(q): raise RuntimeError("rate limited")
        result = await self.coordinator.retrieve("What is quantum entanglement?", local, online, lambda items, q: bool(items))
        self.assertEqual(result.evidence, [])
        self.assertFalse(result.used_online)

    async def test_duplicate_online_and_local_evidence_is_removed(self):
        record = {"title": "T", "content": "same content", "url": "https://example.org/x"}
        async def local(q): return [record]
        async def online(q): return [dict(record)]
        result = await self.coordinator.retrieve("T", local, online, lambda items, q: False)
        self.assertEqual(len(result.evidence), 1)


if __name__ == "__main__":
    unittest.main()
