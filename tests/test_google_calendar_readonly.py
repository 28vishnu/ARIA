import hashlib
import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from cryptography.fernet import Fernet
from integrations import google_calendar_readonly as calendar


class GoogleCalendarReadOnlyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {
            "ARIA_ALERT_DB_PATH": os.path.join(self.temp.name, "alerts.sqlite3"),
            "ARIA_GMAIL_TOKEN_ENCRYPTION_KEY": Fernet.generate_key().decode(),
            "GOOGLE_OAUTH_CLIENT_ID": "test-client",
            "GOOGLE_OAUTH_CLIENT_SECRET": "test-secret",
            "GOOGLE_CALENDAR_REDIRECT_URI": "https://example.test/calendar/oauth/callback",
        })
        self.env.start()
        calendar._ensure_tables()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_tokens_are_encrypted_in_database(self):
        calendar._save_tokens({"refresh_token": "sensitive-refresh-token"})
        with calendar._db() as conn:
            row = conn.execute("SELECT encrypted_json FROM calendar_oauth_tokens WHERE token_id=1").fetchone()
        self.assertNotIn(b"sensitive-refresh-token", row["encrypted_json"])
        self.assertEqual(calendar._load_tokens()["refresh_token"], "sensitive-refresh-token")

    def test_state_is_hashed_before_storage(self):
        raw = "random-state-value"
        with calendar._db() as conn:
            conn.execute("INSERT INTO calendar_oauth_states(state_hash,created_at) VALUES(?,?)", (hashlib.sha256(raw.encode()).hexdigest(), 1.0))
            row = conn.execute("SELECT state_hash FROM calendar_oauth_states").fetchone()
        self.assertNotEqual(raw, row["state_hash"])

    def test_calendar_scope_is_readonly(self):
        self.assertEqual(calendar.CALENDAR_SCOPE, "https://www.googleapis.com/auth/calendar.readonly")
        self.assertNotIn("events", calendar.CALENDAR_SCOPE.replace("calendar.readonly", ""))

    def test_all_day_event_has_no_precise_start(self):
        self.assertIsNone(calendar._event_start({"start": {"date": "2026-10-22"}}))

    def test_timed_event_parses_timezone(self):
        value = calendar._event_start({"start": {"dateTime": "2026-10-22T10:00:00+05:30"}})
        self.assertIsNotNone(value)
        self.assertEqual(value.utcoffset().total_seconds(), 19800)

    def test_missing_encryption_key_fails_closed(self):
        with patch.dict(os.environ, {"ARIA_GMAIL_TOKEN_ENCRYPTION_KEY": ""}):
            with self.assertRaises(RuntimeError):
                calendar._fernet()


if __name__ == "__main__":
    unittest.main()
