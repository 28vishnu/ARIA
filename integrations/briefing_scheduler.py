"""Clock-aware, persistent scheduler for approval-gated ARIA briefings.

The host application injects its existing BackgroundScheduler and BriefingService.
This module prepares morning/evening previews only; it never sends them.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_LOG = logging.getLogger(__name__)


class BriefingClockScheduler:
    """Check the local clock periodically and prepare each day's previews once."""

    def __init__(
        self,
        scheduler: Any,
        briefing_service: Any,
        *,
        db_path: str | None = None,
        timezone_name: str | None = None,
        morning_time: str | None = None,
        evening_time: str | None = None,
        check_interval_seconds: int = 30,
    ) -> None:
        self.scheduler = scheduler
        self.briefing_service = briefing_service
        self.db_path = db_path or os.getenv("ARIA_ALERT_DB_PATH", "/var/data/aria_alerts.sqlite3")
        self.timezone_name = timezone_name or os.getenv("ARIA_BRIEFING_TIMEZONE", "Asia/Kolkata")
        self.morning_time = morning_time or os.getenv("ARIA_BRIEFING_MORNING_TIME", "08:00")
        self.evening_time = evening_time or os.getenv("ARIA_BRIEFING_EVENING_TIME", "19:00")
        self.check_interval_seconds = max(15, int(check_interval_seconds))
        try:
            self.timezone = ZoneInfo(self.timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"Unknown briefing timezone: {self.timezone_name}") from exc
        self._validate_time(self.morning_time, "morning_time")
        self._validate_time(self.evening_time, "evening_time")
        if self.morning_time == self.evening_time:
            raise ValueError("Morning and evening briefing times must differ")
        self.job_id: str | None = None

    @staticmethod
    def _validate_time(value: str, name: str) -> None:
        try:
            parsed = datetime.strptime(value, "%H:%M")
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must use 24-hour HH:MM format") from exc
        if parsed.strftime("%H:%M") != value:
            raise ValueError(f"{name} must use 24-hour HH:MM format")

    def _connect(self) -> sqlite3.Connection:
        path = Path(self.db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(path), timeout=10)
        connection.execute(
            """CREATE TABLE IF NOT EXISTS aria_briefing_runs (
                run_key TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                error_type TEXT
            )"""
        )
        return connection

    def _claim(self, run_key: str, now: datetime) -> bool:
        """Atomically claim a run key; existing keys prevent duplicate previews."""
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO aria_briefing_runs(run_key,status,updated_at) VALUES(?,?,?)",
                (run_key, "running", now.isoformat()),
            )
            return cursor.rowcount == 1

    def _finish(self, run_key: str, now: datetime, error_type: str | None = None) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE aria_briefing_runs SET status=?, updated_at=?, error_type=? WHERE run_key=?",
                ("failed" if error_type else "prepared", now.isoformat(), error_type, run_key),
            )

    async def tick(self, *, now: datetime | None = None) -> None:
        """Run due previews. The supplied `now` exists to make tests deterministic."""
        current = now.astimezone(self.timezone) if now and now.tzinfo else (
            now.replace(tzinfo=self.timezone) if now else datetime.now(self.timezone)
        )
        local_day = current.strftime("%Y-%m-%d")
        due: list[tuple[str, str]] = []
        if current.strftime("%H:%M") >= self.morning_time:
            due.append(("morning", f"{local_day}:morning"))
        if current.strftime("%H:%M") >= self.evening_time:
            due.append(("evening", f"{local_day}:evening"))

        for period, run_key in due:
            if not self._claim(run_key, current):
                continue
            try:
                method = getattr(self.briefing_service, f"prepare_{period}")
                await method()
                self._finish(run_key, current)
                _LOG.info("Prepared %s briefing preview for %s; owner approval required", period, local_day)
            except Exception as exc:
                self._finish(run_key, current, type(exc).__name__)
                _LOG.exception("Failed to prepare %s briefing preview", period)

    def start(self) -> str:
        """Register one recurring clock check with ARIA's existing scheduler."""
        if self.job_id is not None:
            return self.job_id
        self.job_id = self.scheduler.schedule_recurring(
            self.check_interval_seconds,
            self.tick,
            goal_id="aria_approval_gated_briefing_clock",
            timeout_seconds=60,
            run_immediately=True,
        )
        return self.job_id
