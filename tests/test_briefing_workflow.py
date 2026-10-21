import asyncio
import os
import tempfile
import unittest

from integrations.briefing_workflow import BriefingWorkflow


class BriefingWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workflow = BriefingWorkflow(os.path.join(self.tmp.name, "briefings.sqlite3"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_prepare_persists_preview_without_sending(self):
        preview = self.workflow.prepare([{"source": "gmail", "title": "New message"}], period="morning")
        self.assertEqual(preview["status"], "pending_approval")
        self.assertFalse(preview["sent"])
        saved = self.workflow.get_preview(preview["briefing_id"])
        self.assertEqual(saved["status"], "pending_approval")
        self.assertIn("New message", saved["text"])

    def test_denies_without_explicit_approval_and_does_not_call_notifier(self):
        preview = self.workflow.prepare([{"source": "calendar", "title": "Meeting"}])
        calls = []
        async def notifier(message):
            calls.append(message)
            return True
        result = asyncio.run(self.workflow.approve_and_send(preview["briefing_id"], owner_approved=False, notifier=notifier))
        self.assertFalse(result["sent"])
        self.assertEqual(calls, [])

    def test_sends_only_after_approval_and_is_idempotent(self):
        preview = self.workflow.prepare([{"source": "github", "title": "New commit"}])
        calls = []
        async def notifier(message):
            calls.append(message)
            return True
        first = asyncio.run(self.workflow.approve_and_send(preview["briefing_id"], owner_approved=True, notifier=notifier))
        second = asyncio.run(self.workflow.approve_and_send(preview["briefing_id"], owner_approved=True, notifier=notifier))
        self.assertTrue(first["sent"])
        self.assertTrue(second["sent"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.workflow.get_preview(preview["briefing_id"])["status"], "delivered")

    def test_failed_delivery_returns_to_approval_queue(self):
        preview = self.workflow.prepare([{"source": "system", "title": "Test"}])
        async def notifier(message):
            return False
        result = asyncio.run(self.workflow.approve_and_send(preview["briefing_id"], owner_approved=True, notifier=notifier))
        self.assertFalse(result["sent"])
        self.assertEqual(self.workflow.get_preview(preview["briefing_id"])["status"], "pending_approval")

    def test_unknown_id_is_safe(self):
        async def notifier(message):
            return True
        result = asyncio.run(self.workflow.approve_and_send("unknown", owner_approved=True, notifier=notifier))
        self.assertEqual(result["status"], "not_found")


if __name__ == "__main__":
    unittest.main()
