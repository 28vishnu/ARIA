import asyncio
import logging

logger = logging.getLogger("aria")


class TelegramStatus:
    def __init__(self, http_client, token, chat_id):
        self.http_client = http_client
        self.token = token
        self.chat_id = chat_id
        self.message_id = None

    @property
    def api_url(self):
        return f"https://api.telegram.org/bot{self.token}"

    async def start(self, text="Reading your request..."):
        try:
            response = await self.http_client.post(
                f"{self.api_url}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                },
            )

            response.raise_for_status()
            data = response.json()

            self.message_id = data["result"]["message_id"]

        except Exception:
            logger.exception("[TelegramStatus] Failed to create status message.")

    async def update(self, text):
        if self.message_id is None:
            return

        try:
            await self.http_client.post(
                f"{self.api_url}/editMessageText",
                json={
                    "chat_id": self.chat_id,
                    "message_id": self.message_id,
                    "text": text,
                },
            )

        except Exception:
            logger.exception("[TelegramStatus] Failed to update status.")

    async def delete(self):
        if self.message_id is None:
            return

        try:
            await self.http_client.post(
                f"{self.api_url}/deleteMessage",
                json={
                    "chat_id": self.chat_id,
                    "message_id": self.message_id,
                },
            )

        except Exception:
            logger.exception("[TelegramStatus] Failed to delete status.")

        finally:
            self.message_id = None