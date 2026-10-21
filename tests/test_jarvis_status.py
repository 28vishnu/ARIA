import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from integrations.jarvis_status import build_status


class JarvisStatusTests(unittest.TestCase):
    def test_no_secrets_or_content_in_response(self):
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / "aria.sqlite3")
            status = build_status(path, {
                "TELEGRAM_BOT_TOKEN": "secret-token", "ADMIN_CHAT_ID": "123",
                "GITHUB_WEBHOOK_SECRET": "webhook-secret",
            })
            rendered = repr(status)
            self.assertNotIn("secret-token", rendered)
            self.assertNotIn("webhook-secret", rendered)
            self.assertTrue(status["integrations"]["telegram_notifications"]["configured"])

    def test_detects_token_rows_and_pending_alerts(self):
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / "aria.sqlite3")
            conn = sqlite3.connect(path)
            conn.executescript("""
                CREATE TABLE gmail_oauth_tokens (token_id INTEGER PRIMARY KEY, encrypted_json BLOB);
                INSERT INTO gmail_oauth_tokens VALUES (1, X'01');
                CREATE TABLE calendar_oauth_tokens (token_id INTEGER PRIMARY KEY, encrypted_json BLOB);
                CREATE TABLE drive_oauth_tokens (token_id INTEGER PRIMARY KEY, encrypted_json BLOB);
                CREATE TABLE alerts (status TEXT);
                INSERT INTO alerts VALUES ('pending_immediate');
                INSERT INTO alerts VALUES ('pending_digest');
                INSERT INTO alerts VALUES ('delivered');
            """)
            conn.close()
            status = build_status(path, {})
            self.assertTrue(status["integrations"]["gmail_readonly"]["connected"])
            self.assertFalse(status["integrations"]["google_calendar_readonly"]["connected"])
            self.assertEqual(status["alerts"]["pending_urgent"], 1)
            self.assertEqual(status["alerts"]["pending_digest"], 1)

    def test_missing_database_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            status = build_status(str(Path(d) / "missing.sqlite3"), {})
            self.assertFalse(status["database"]["exists"])
            self.assertFalse(status["database"]["readable"])
            self.assertFalse(status["integrations"]["google_drive_readonly"]["connected"])

    def test_initialized_empty_token_tables_are_not_connected(self):
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / "aria.sqlite3")
            conn = sqlite3.connect(path)
            conn.executescript("""
                CREATE TABLE gmail_oauth_tokens (token_id INTEGER PRIMARY KEY, encrypted_json BLOB);
                CREATE TABLE calendar_oauth_tokens (token_id INTEGER PRIMARY KEY, encrypted_json BLOB);
                CREATE TABLE drive_oauth_tokens (token_id INTEGER PRIMARY KEY, encrypted_json BLOB);
                CREATE TABLE alerts (status TEXT);
            """)
            conn.close()
            status = build_status(path, {})
            self.assertFalse(status["integrations"]["gmail_readonly"]["connected"])
            self.assertEqual(status["alerts"]["pending_urgent"], 0)


if __name__ == "__main__":
    unittest.main()
