"""Read recent, already-ingested ARIA alerts into approval-gated briefings.

This collector does not call provider APIs or alter alert status. It only reads
the shared SQLite alert queue. Gmail/Calendar pollers and authenticated GitHub
webhooks must already have ingested events for them to appear here.
"""
from __future__ import annotations

import os
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

_SOURCE_ALIASES = {
    "gmail": ("gmail",),
    "calendar": ("google calendar", "calendar"),
    "github": ("github",),
    "drive": ("google drive", "drive"),
    "system": ("aria", "system"),
}


def create_alert_collector(source: str, db_path: str | None = None, *, lookback_hours: int = 24, limit: int = 30) -> Callable[[], Any]:
    """Create an async collector returning normalized recent alert items."""
    normalized_source = str(source).strip().lower()
    if normalized_source not in _SOURCE_ALIASES:
        raise ValueError(f"Unsupported briefing source: {source}")
    path = db_path or os.getenv("ARIA_ALERT_DB_PATH", "./aria_data/alerts.sqlite3")
    lookback_seconds = max(1, min(int(lookback_hours), 168)) * 3600
    max_rows = max(1, min(int(limit), 100))
    aliases = _SOURCE_ALIASES[normalized_source]

    async def collect() -> list[dict[str, Any]]:
        if path != ":memory:" and not Path(path).exists():
            return []
        with sqlite3.connect(path, timeout=5) as connection:
            connection.row_factory = sqlite3.Row
            try:
                rows = connection.execute(
                    "SELECT source,title,body,severity,created_at FROM alerts "
                    "WHERE created_at >= ? ORDER BY created_at DESC LIMIT ?",
                    (time.time() - lookback_seconds, max_rows * 5),
                ).fetchall()
            except sqlite3.OperationalError as exc:
                if "no such table" in str(exc).lower():
                    return []
                raise
        items: list[dict[str, Any]] = []
        for row in rows:
            provider = str(row["source"] or "").strip().lower()
            if not any(alias in provider for alias in aliases):
                continue
            severity = str(row["severity"] or "info").lower()
            priority = {"urgent": "urgent", "important": "high", "info": "normal"}.get(severity, "normal")
            items.append({
                "source": normalized_source,
                "title": str(row["title"] or "")[:180],
                "detail": str(row["body"] or "")[:360],
                "priority": priority,
                "occurred_at": str(row["created_at"]),
            })
            if len(items) >= max_rows:
                break
        return items

    return collect


__all__ = ["create_alert_collector"]
