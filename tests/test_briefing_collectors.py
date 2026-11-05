import os
import sqlite3
import tempfile
import time
import unittest

from integrations.briefing_collectors import create_alert_collector


class BriefingCollectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_collects_recent_matching_source_without_mutating_alerts(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "alerts.sqlite3")
            with sqlite3.connect(path) as conn:
                conn.execute("""CREATE TABLE alerts (
                    id INTEGER PRIMARY KEY, source TEXT, title TEXT, body TEXT,
                    severity TEXT, created_at REAL, dedupe_key TEXT, status TEXT
                )""")
                conn.execute(
                    "INSERT INTO alerts(source,title,body,severity,created_at,dedupe_key,status) VALUES(?,?,?,?,?,?,?)",
                    ("GitHub", "Workflow failed", "Build failed", "urgent", time.time(), "x1", "delivered"),
                )
                conn.execute(
                    "INSERT INTO alerts(source,title,body,severity,created_at,dedupe_key,status) VALUES(?,?,?,?,?,?,?)",
                    ("Gmail", "New email", "Some details", "important", time.time(), "x2", "pending_digest"),
                )
            collector = create_alert_collector("github", path)
            items = await collector()
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["title"], "Workflow failed")
            self.assertEqual(items[0]["source"], "github")
            self.assertEqual(items[0]["priority"], "urgent")
            with sqlite3.connect(path) as conn:
                statuses = [row[0] for row in conn.execute("SELECT status FROM alerts ORDER BY id")]
            self.assertEqual(statuses, ["delivered", "pending_digest"])

    async def test_missing_database_returns_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            items = await create_alert_collector("gmail", os.path.join(directory, "missing.sqlite3"))()
            self.assertEqual(items, [])

    async def test_invalid_source_rejected(self):
        with self.assertRaises(ValueError):
            create_alert_collector("calendarish", ":memory:")

    async def test_severity_normalization(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "alerts.sqlite3")
            with sqlite3.connect(path) as conn:
                conn.execute("CREATE TABLE alerts (source TEXT,title TEXT,body TEXT,severity TEXT,created_at REAL)")
                conn.execute("INSERT INTO alerts VALUES(?,?,?,?,?)", ("Google Calendar", "Appointment", "Starts soon", "important", time.time()))
            items = await create_alert_collector("calendar", path)()
            self.assertEqual(items[0]["priority"], "high")


if __name__ == "__main__":
    unittest.main()
