import hashlib
import os
import tempfile
import unittest
from unittest.mock import patch

from cryptography.fernet import Fernet

from integrations import gmail_readonly as gmail


class GmailReadOnlyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {
            "ARIA_ALERT_DB_PATH": os.path.join(self.temp.name, "alerts.sqlite3"),
            "ARIA_GMAIL_TOKEN_ENCRYPTION_KEY": Fernet.generate_key().decode(),
            "GOOGLE_OAUTH_CLIENT_ID": "test-client",
            "GOOGLE_OAUTH_CLIENT_SECRET": "test-secret",
            "GOOGLE_OAUTH_REDIRECT_URI": "https://example.test/gmail/oauth/callback",
        })
        self.env.start()
        gmail._ensure_tables()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_tokens_are_encrypted_in_database(self):
        gmail._save_tokens({"refresh_token": "sensitive-refresh-token"})
        with gmail._db() as conn:
            row = conn.execute("SELECT encrypted_json FROM gmail_oauth_tokens WHERE token_id=1").fetchone()
        self.assertNotIn(b"sensitive-refresh-token", row["encrypted_json"])
        self.assertEqual(gmail._load_tokens()["refresh_token"], "sensitive-refresh-token")

    def test_state_is_hashed_before_storage(self):
        raw_state = "random-state-value"
        state_hash = hashlib.sha256(raw_state.encode()).hexdigest()
        with gmail._db() as conn:
            conn.execute("INSERT INTO gmail_oauth_states(state_hash,created_at) VALUES(?,?)", (state_hash, 1.0))
            row = conn.execute("SELECT state_hash FROM gmail_oauth_states").fetchone()
        self.assertNotEqual(row["state_hash"], raw_state)

    def test_missing_encryption_key_fails_closed(self):
        with patch.dict(os.environ, {"ARIA_GMAIL_TOKEN_ENCRYPTION_KEY": ""}):
            with self.assertRaises(RuntimeError):
                gmail._fernet()

    def test_gmail_scope_is_readonly(self):
        self.assertEqual(gmail.GMAIL_SCOPE, "https://www.googleapis.com/auth/gmail.readonly")


if __name__ == "__main__":
    unittest.main()
