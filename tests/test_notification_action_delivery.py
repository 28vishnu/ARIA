import os
import unittest
from unittest.mock import patch

from actions.actions.notification import NotificationAction


class NotificationActionTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_credentials_does_not_claim_delivery(self):
        with patch.dict(os.environ, {}, clear=True):
            action = NotificationAction(telegram_token="", chat_id="")
            result = await action.execute({"message": "test alert"})
        self.assertFalse(result.success)
        self.assertEqual(result.data, {"delivered": False})
        self.assertIn("not configured", result.error)

    async def test_empty_message_fails_validation(self):
        action = NotificationAction(telegram_token="token", chat_id="123")
        result = await action.execute({"message": "   "})
        self.assertFalse(result.success)
        self.assertIn("required", result.error)

    async def test_oversized_message_fails_validation(self):
        action = NotificationAction(telegram_token="token", chat_id="123")
        self.assertFalse(await action.validate({"message": "x" * 12001}))


if __name__ == "__main__":
    unittest.main()
