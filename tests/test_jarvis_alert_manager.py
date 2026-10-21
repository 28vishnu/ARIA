import asyncio
import tempfile
import unittest
from pathlib import Path

from integrations.alert_manager import AlertManager


class AlertManagerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.temp.name) / "alerts.sqlite3")
        self.sent = []

        async def notifier(message):
            self.sent.append(message)
            return True

        self.manager = AlertManager(self.db, notifier)

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def test_urgent_is_sent_immediately(self):
        alert, created, delivered = await self.manager.enqueue_and_dispatch(
            source="gmail", title="Security alert", body="New sign-in detected", severity="urgent")
        self.assertTrue(created)
        self.assertTrue(delivered)
        self.assertEqual(alert.status, "delivered")
        self.assertEqual(len(self.sent), 1)
        self.assertIn("URGENT", self.sent[0])

    async def test_nonurgent_waits_for_digest(self):
        _, created, delivered = await self.manager.enqueue_and_dispatch(
            source="calendar", title="Meeting tomorrow", body="Project review", severity="important")
        self.assertTrue(created)
        self.assertIsNone(delivered)
        self.assertEqual(self.sent, [])
        result = await self.manager.send_digest()
        self.assertTrue(result["sent"])
        self.assertEqual(result["count"], 1)
        self.assertIn("Meeting tomorrow", self.sent[0])

    async def test_duplicate_is_not_resent(self):
        kwargs = dict(source="github", title="New commit", body="abc", severity="urgent", dedupe_key="repo:sha")
        await self.manager.enqueue_and_dispatch(**kwargs)
        _, created_again, delivered_again = await self.manager.enqueue_and_dispatch(**kwargs)
        self.assertFalse(created_again)
        self.assertIsNone(delivered_again)
        self.assertEqual(len(self.sent), 1)

    async def test_invalid_severity_rejected(self):
        with self.assertRaises(ValueError):
            self.manager.enqueue(source="x", title="t", body="b", severity="automatic")

    async def test_failed_delivery_remains_pending(self):
        async def failing(_message):
            return False
        manager = AlertManager(self.db, failing)
        alert, _, delivered = await manager.enqueue_and_dispatch(
            source="gmail", title="Alert", body="Needs retry", severity="urgent")
        self.assertFalse(delivered)
        self.assertEqual(alert.status, "pending_immediate")
        self.assertGreaterEqual(manager.pending_count(), 1)


if __name__ == "__main__":
    unittest.main()
