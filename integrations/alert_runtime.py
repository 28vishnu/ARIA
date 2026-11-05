"""Scheduler adapter for ARIA's urgent alerts and twice-daily digests.

This module only sends notifications; it never sends email or changes user data.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from integrations.alert_manager import AlertManager

logger = logging.getLogger("aria")


async def telegram_notifier(message: str) -> bool:
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN") or "").strip()
    chat_id = (
        os.getenv("ADMIN_CHAT_ID")
        or os.getenv("TELEGRAM_CHAT_ID")
        or os.getenv("ALLOWED_TELEGRAM_USER_ID")
        or ""
    ).strip()
    if not token or not chat_id or not message.strip():
        logger.warning("[JARVIS alerts] Telegram notifier is not configured.")
        return False
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            # Split conservatively below Telegram's message length limit.
            chunks = [message[i:i + 3900] for i in range(0, len(message), 3900)]
            for chunk in chunks:
                response = await client.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat_id, "text": chunk, "disable_web_page_preview": True},
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict) or not payload.get("ok"):
                    logger.warning("[JARVIS alerts] Telegram API did not confirm delivery.")
                    return False
        return True
    except Exception:
        logger.exception("[JARVIS alerts] Telegram delivery failed.")
        return False


class AlertRuntime:
    """Ticked by ARIA's existing BackgroundScheduler every minute."""

    def __init__(self, manager: AlertManager | None = None, now=None):
        self.manager = manager or AlertManager(notifier=telegram_notifier)
        self._now = now or (lambda: datetime.now(self._timezone()))
        self.timezone_name = os.getenv("ARIA_TIMEZONE", "Asia/Kolkata")
        self.morning_time = os.getenv("ARIA_BRIEFING_MORNING_TIME", os.getenv("ARIA_MORNING_BRIEFING", "08:00"))
        self.evening_time = os.getenv("ARIA_BRIEFING_EVENING_TIME", os.getenv("ARIA_EVENING_BRIEFING", "19:00"))
        self._validate_clock(self.morning_time, "ARIA_MORNING_BRIEFING")
        self._validate_clock(self.evening_time, "ARIA_EVENING_BRIEFING")
        self._ensure_state_table()

    def _timezone(self):
        try:
            return ZoneInfo(os.getenv("ARIA_TIMEZONE", "Asia/Kolkata"))
        except ZoneInfoNotFoundError as exc:
            raise ValueError("ARIA_TIMEZONE must be a valid IANA timezone") from exc

    @staticmethod
    def _validate_clock(value: str, name: str) -> None:
        try:
            hour, minute = value.split(":", 1)
            if len(hour) != 2 or len(minute) != 2:
                raise ValueError
            if not (0 <= int(hour) <= 23 and 0 <= int(minute) <= 59):
                raise ValueError
        except (ValueError, AttributeError):
            raise ValueError(f"{name} must use HH:MM in 24-hour time")

    def _ensure_state_table(self):
        with self.manager._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS alert_runtime_state (
                    state_key TEXT PRIMARY KEY,
                    state_value TEXT NOT NULL
                )
            """)

    def _already_ran(self, key: str, date_key: str) -> bool:
        with self.manager._connect() as conn:
            row = conn.execute(
                "SELECT state_value FROM alert_runtime_state WHERE state_key=?",
                (key,),
            ).fetchone()
        return bool(row and row["state_value"] == date_key)

    def _mark_ran(self, key: str, date_key: str):
        with self.manager._connect() as conn:
            conn.execute(
                "INSERT INTO alert_runtime_state(state_key,state_value) VALUES(?,?) "
                "ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value",
                (key, date_key),
            )

    async def tick(self) -> dict[str, Any]:
        """Retry pending urgent alerts and send due morning/evening digests."""
        now = self._now()
        date_key = now.date().isoformat()
        retried = 0
        for alert_id in self.manager.pending_urgent_ids():
            if await self.manager.dispatch_urgent(alert_id):
                retried += 1

        due = []
        clock = now.strftime("%H:%M")
        # Send only the most recent due digest if the process was offline across
        # both scheduled times. This avoids sending an overdue morning digest at
        # night and then immediately sending a second, empty evening digest.
        scheduled_periods = (
            [("evening", self.evening_time)]
            if clock >= self.evening_time
            else ([ ("morning", self.morning_time) ] if clock >= self.morning_time else [])
        )
        for key, scheduled in scheduled_periods:
            # A >= comparison tolerates scheduler jitter, process wake-up and
            # brief restarts. Persistent per-day state still prevents duplicates.
            if not self._already_ran(key, date_key):
                result = await self.manager.send_digest()
                if result.get("sent") or result.get("reason") == "empty":
                    self._mark_ran(key, date_key)
                due.append({"briefing": key, **result})
        return {"retried_urgent": retried, "briefings": due}
