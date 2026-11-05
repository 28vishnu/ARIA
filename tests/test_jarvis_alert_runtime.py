import asyncio
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from integrations.alert_manager import AlertManager
from integrations.alert_runtime import AlertRuntime


class AlertRuntimeTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_morning_digest_runs_once_per_day(self):
        now = [datetime(2026, 10, 22, 8, 0, tzinfo=ZoneInfo("Asia/Kolkata"))]
        runtime = AlertRuntime(self.manager, now=lambda: now[0])
        self.manager.enqueue(source="github", title="CI passed", body="Build is green")
        first = await runtime.tick()
        second = await runtime.tick()
        self.assertEqual(len(first["briefings"]), 1)
        self.assertTrue(first["briefings"][0]["sent"])
        self.assertEqual(second["briefings"], [])
        self.assertEqual(len(self.sent), 1)

    async def test_evening_digest_runs_at_configured_time(self):
        now = [datetime(2026, 10, 22, 20, 0, tzinfo=ZoneInfo("Asia/Kolkata"))]
        runtime = AlertRuntime(self.manager, now=lambda: now[0])
        self.manager.enqueue(source="calendar", title="Tomorrow", body="Meeting at 10")
        result = await runtime.tick()
        self.assertEqual(result["briefings"][0]["briefing"], "evening")
        self.assertTrue(result["briefings"][0]["sent"])

    async def test_pending_urgent_alert_is_retried(self):
        attempts = []
        async def notifier(message):
            attempts.append(message)
            return len(attempts) > 1
        manager = AlertManager(self.db, notifier)
        _, _, first = await manager.enqueue_and_dispatch(
            source="gmail", title="Security", body="Sign-in", severity="urgent"
        )
        self.assertFalse(first)
        runtime = AlertRuntime(manager, now=lambda: datetime(2026, 10, 22, 12, 0, tzinfo=ZoneInfo("Asia/Kolkata")))
        result = await runtime.tick()
        self.assertEqual(result["retried_urgent"], 1)
        self.assertEqual(len(attempts), 2)

    async def test_invalid_briefing_time_rejected(self):
        import os
        old = os.environ.get("ARIA_MORNING_BRIEFING")
        os.environ["ARIA_MORNING_BRIEFING"] = "25:99"
        try:
            with self.assertRaises(ValueError):
                AlertRuntime(self.manager, now=lambda: datetime.now(ZoneInfo("Asia/Kolkata")))
        finally:
            if old is None:
                os.environ.pop("ARIA_MORNING_BRIEFING", None)
            else:
                os.environ["ARIA_MORNING_BRIEFING"] = old


if __name__ == "__main__":
    unittest.main()
