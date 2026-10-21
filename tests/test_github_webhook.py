import hashlib
import hmac
import json
import os
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from integrations.github_webhook import _summarize_event, _verify_signature, github_webhook


class GithubWebhookTests(unittest.TestCase):
    def test_signature_valid_and_invalid(self):
        body = b'{"action":"opened"}'
        signature = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
        self.assertTrue(_verify_signature("secret", body, signature))
        self.assertFalse(_verify_signature("secret", body, "sha256=bad"))
        self.assertFalse(_verify_signature("", body, signature))

    def test_failed_workflow_is_urgent(self):
        summary = _summarize_event("workflow_run", {
            "repository": {"full_name": "owner/repo"},
            "workflow_run": {"name": "Tests", "conclusion": "failure", "html_url": "https://github.com/owner/repo/actions/runs/1"},
        })
        self.assertEqual(summary[2], "urgent")
        self.assertIn("owner/repo", summary[1])

    def test_successful_workflow_is_digest(self):
        summary = _summarize_event("workflow_run", {
            "repository": {"full_name": "owner/repo"},
            "workflow_run": {"name": "Tests", "conclusion": "success"},
        })
        self.assertEqual(summary[2], "important")

    def test_unhandled_event_ignored(self):
        self.assertIsNone(_summarize_event("issues", {"action": "opened"}))


class EndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_missing_secret(self):
        request = AsyncMock()
        request.body.return_value = b'{}'
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(HTTPException) as ctx:
                await github_webhook(request, "sha256=anything", "push", "delivery-1")
        self.assertEqual(ctx.exception.status_code, 503)

    async def test_rejects_bad_signature(self):
        request = AsyncMock()
        request.body.return_value = b'{}'
        with patch.dict(os.environ, {"GITHUB_WEBHOOK_SECRET": "secret"}, clear=True):
            with self.assertRaises(HTTPException) as ctx:
                await github_webhook(request, "sha256=bad", "push", "delivery-1")
        self.assertEqual(ctx.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
