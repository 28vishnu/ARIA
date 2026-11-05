"""Notification action with truthful Telegram delivery status.

Previously this action logged a message and returned delivered=True without
actually delivering it. This replacement sends through Telegram only when the
bot token and destination are configured; otherwise it fails closed.
"""
import logging
import os
from typing import Any, Dict

import httpx

from actions.base import BaseAction, ActionResult

logger = logging.getLogger("aria")


class NotificationAction(BaseAction):
    name = "notification_action"
    description = "Sends a notification through the configured Telegram bot."
    permission_level = "safe"
    timeout_seconds = 15.0

    def __init__(self, telegram_token: str | None = None, chat_id: str | None = None,
                 http_timeout: float = 10.0):
        self.telegram_token = (telegram_token or os.getenv("TELEGRAM_BOT_TOKEN")
                               or os.getenv("TELEGRAM_TOKEN") or "").strip()
        self.chat_id = (chat_id or os.getenv("ADMIN_CHAT_ID")
                        or os.getenv("TELEGRAM_CHAT_ID") or "").strip()
        self.http_timeout = max(3.0, float(http_timeout))

    async def validate(self, params: Dict[str, Any]) -> bool:
        message = str(params.get("message") or "").strip()
        return bool(message and len(message) <= 12000)

    async def execute(self, params: Dict[str, Any]) -> ActionResult:
        if not await self.validate(params):
            return ActionResult(success=False, action_name=self.name,
                                error="A non-empty message of at most 12000 characters is required.")
        if not self.telegram_token or not self.chat_id:
            return ActionResult(success=False, action_name=self.name,
                                data={"delivered": False},
                                error="Telegram delivery is not configured (set TELEGRAM_BOT_TOKEN and ADMIN_CHAT_ID).")
        message = str(params["message"]).strip()
        chunks = [message[i:i + 3900] for i in range(0, len(message), 3900)]
        delivered_chunks = 0
        try:
            async with httpx.AsyncClient(timeout=self.http_timeout) as client:
                for chunk in chunks:
                    response = await client.post(
                        f"https://api.telegram.org/bot{self.telegram_token}/sendMessage",
                        json={"chat_id": self.chat_id, "text": chunk, "disable_web_page_preview": True},
                    )
                    response.raise_for_status()
                    payload = response.json()
                    if not isinstance(payload, dict) or not payload.get("ok"):
                        raise RuntimeError("Telegram API did not confirm message delivery.")
                    delivered_chunks += 1
            logger.info("[NotificationAction] Telegram delivered %s chunk(s).", delivered_chunks)
            return ActionResult(success=True, action_name=self.name,
                                data={"delivered": True, "channel": "telegram", "chunks": delivered_chunks})
        except Exception as exc:
            logger.warning("[NotificationAction] Telegram delivery failed: %s", exc)
            return ActionResult(success=False, action_name=self.name,
                                data={"delivered": False, "channel": "telegram", "chunks_delivered": delivered_chunks},
                                error=f"Telegram delivery failed: {type(exc).__name__}")
