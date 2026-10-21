import asyncio
import os
import tempfile
import unittest
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from integrations.briefing_scheduler import BriefingClockScheduler


class FakeService:
    def __init__(self):
        self.calls = []
    async def prepare_morning(self):
        self.calls.append("morning")
        return {"sent": False}
    async def prepare_evening(self):
        self.calls.append("evening")
        return {"sent": False}


class FakeScheduler:
    def __init__(self):
        self.kwargs = None
    def schedule_recurring(self, interval, func, *args, **kwargs):
        self.kwargs = (interval, func, args, kwargs)
        return "job-1"


class BriefingSchedulerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "alerts.sqlite3")
        self.service = FakeService()
        self.scheduler = FakeScheduler()
        self.clock = BriefingClockScheduler(self.scheduler, self.service, db_path=self.db,
            timezone_name="Asia/Kolkata", morning_time="08:00", evening_time="19:00")
    def tearDown(self):
        self.tmp.cleanup()

    def test_before_morning_does_nothing(self):
        asyncio.run(self.clock.tick(now=datetime(2026, 1, 2, 7, 59, tzinfo=ZoneInfo("Asia/Kolkata"))))
        self.assertEqual(self.service.calls, [])

    def test_morning_once_even_after_repeated_ticks(self):
        now = datetime(2026, 1, 2, 8, 1, tzinfo=ZoneInfo("Asia/Kolkata"))
        asyncio.run(self.clock.tick(now=now))
        asyncio.run(self.clock.tick(now=now))
        self.assertEqual(self.service.calls, ["morning"])

    def test_evening_runs_both_if_service_was_not_started_until_evening(self):
        now = datetime(2026, 1, 2, 19, 1, tzinfo=ZoneInfo("Asia/Kolkata"))
        asyncio.run(self.clock.tick(now=now))
        self.assertEqual(self.service.calls, ["morning", "evening"])

    def test_persistent_dedupe_across_instances(self):
        now = datetime(2026, 1, 2, 8, 1, tzinfo=ZoneInfo("Asia/Kolkata"))
        asyncio.run(self.clock.tick(now=now))
        other_service = FakeService()
        other = BriefingClockScheduler(self.scheduler, other_service, db_path=self.db,
            timezone_name="Asia/Kolkata", morning_time="08:00", evening_time="19:00")
        asyncio.run(other.tick(now=now))
        self.assertEqual(other_service.calls, [])

    def test_start_registers_recurring_clock_check(self):
        self.assertEqual(self.clock.start(), "job-1")
        self.assertEqual(self.scheduler.kwargs[0], 30)
        self.assertTrue(self.scheduler.kwargs[3]["run_immediately"])

    def test_invalid_time_rejected(self):
        with self.assertRaises(ValueError):
            BriefingClockScheduler(self.scheduler, self.service, db_path=self.db, morning_time="8am")


if __name__ == "__main__":
    unittest.main()
