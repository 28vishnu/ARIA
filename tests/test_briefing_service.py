import asyncio
import tempfile
import unittest
from pathlib import Path

from integrations.briefing_service import BriefingService
from integrations.briefing_workflow import BriefingWorkflow


class BriefingServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workflow = BriefingWorkflow(str(Path(self.tmp.name) / "briefings.sqlite3"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_prepares_preview_without_sending(self):
        async def gmail():
            return [{"title": "Unread mail", "detail": "Review", "priority": "high"}]
        result = asyncio.run(BriefingService(self.workflow, {"gmail": gmail}).prepare_morning())
        self.assertEqual(result["status"], "pending_approval")
        self.assertFalse(result["sent"])
        self.assertTrue(result["requires_owner_approval"])
        self.assertEqual(result["sources"]["gmail"], "ok")
        self.assertIn("GMAIL: Unread mail", result["text"])

    def test_failed_source_does_not_block_other_sources(self):
        async def broken():
            raise RuntimeError("sensitive provider details must not be logged")
        async def calendar():
            return [{"title": "Meeting", "priority": "urgent"}]
        result = asyncio.run(BriefingService(self.workflow, {"gmail": broken, "calendar": calendar}).prepare())
        self.assertEqual(result["sources"]["gmail"], "unavailable (RuntimeError)")
        self.assertEqual(result["sources"]["calendar"], "ok")
        self.assertIn("CALENDAR: Meeting", result["text"])

    def test_overwrites_untrusted_source_field(self):
        async def github():
            return [{"source": "gmail", "title": "Commit"}]
        result = asyncio.run(BriefingService(self.workflow, {"github": github}).prepare())
        self.assertIn("GITHUB: Commit", result["text"])
        self.assertNotIn("GMAIL: Commit", result["text"])

    def test_rejects_unknown_source(self):
        with self.assertRaises(ValueError):
            BriefingService(self.workflow, {"dropbox": lambda: None})

    def test_requires_async_collector(self):
        service = BriefingService(self.workflow, {"gmail": lambda: []})
        result = asyncio.run(service.prepare())
        self.assertEqual(result["sources"]["gmail"], "unavailable (TypeError)")

    def test_caps_items_per_source(self):
        async def drive():
            return [{"title": f"Doc {i}"} for i in range(10)]
        result = asyncio.run(BriefingService(self.workflow, {"drive": drive}, max_items_per_source=2).prepare())
        self.assertEqual(result["metadata"]["counts_by_source"]["drive"], 2)


if __name__ == "__main__":
    unittest.main()
