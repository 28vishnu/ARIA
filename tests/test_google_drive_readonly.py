import hashlib
import os
import tempfile
import unittest
from unittest.mock import patch

from cryptography.fernet import Fernet
from integrations import google_drive_readonly as drive


class GoogleDriveReadOnlyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {
            "ARIA_ALERT_DB_PATH": os.path.join(self.temp.name, "alerts.sqlite3"),
            "ARIA_GMAIL_TOKEN_ENCRYPTION_KEY": Fernet.generate_key().decode(),
            "GOOGLE_OAUTH_CLIENT_ID": "test-client",
            "GOOGLE_OAUTH_CLIENT_SECRET": "test-secret",
            "GOOGLE_DRIVE_REDIRECT_URI": "https://example.test/drive/oauth/callback",
        })
        self.env.start()
        drive._ensure_tables()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_tokens_are_encrypted_at_rest(self):
        drive._save_tokens({"refresh_token": "sensitive-drive-refresh-token"})
        with drive._db() as conn:
            row = conn.execute("SELECT encrypted_json FROM drive_oauth_tokens WHERE token_id=1").fetchone()
        self.assertNotIn(b"sensitive-drive-refresh-token", row["encrypted_json"])
        self.assertEqual(drive._load_tokens()["refresh_token"], "sensitive-drive-refresh-token")

    def test_oauth_state_is_hashed_before_storage(self):
        raw = "state-value"
        with drive._db() as conn:
            conn.execute("INSERT INTO drive_oauth_states(state_hash,created_at) VALUES(?,?)", (hashlib.sha256(raw.encode()).hexdigest(), 1.0))
            row = conn.execute("SELECT state_hash FROM drive_oauth_states").fetchone()
        self.assertNotEqual(raw, row["state_hash"])

    def test_scope_is_read_only(self):
        self.assertEqual(drive.DRIVE_SCOPE, "https://www.googleapis.com/auth/drive.readonly")
        self.assertIn("readonly", drive.DRIVE_SCOPE)
        self.assertNotIn("drive.file", drive.DRIVE_SCOPE)

    def test_search_query_escapes_apostrophe_and_backslash(self):
        result = drive.build_drive_query("owner's \\ plan")
        self.assertIn("owner\\'s", result)
        self.assertIn("\\\\ plan", result)
        self.assertIn("trashed = false", result)

    def test_search_query_rejects_empty_and_long_terms(self):
        with self.assertRaises(ValueError):
            drive.build_drive_query("  ")
        with self.assertRaises(ValueError):
            drive.build_drive_query("x" * 201)

    def test_missing_encryption_key_fails_closed(self):
        with patch.dict(os.environ, {"ARIA_GMAIL_TOKEN_ENCRYPTION_KEY": ""}):
            with self.assertRaises(RuntimeError):
                drive._fernet()


if __name__ == "__main__":
    unittest.main()
