"""Persistent, consent-friendly alert queue for ARIA JARVIS.

Urgent alerts are delivered immediately by an injected async notifier. All other
alerts are held for a digest. This module deliberately does not connect to any
external account or execute user actions.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

Notifier = Callable[[str], Awaitable[bool]]
VALID_SEVERITIES = {"urgent", "important", "info"}


@dataclass(frozen=True)
class Alert:
    alert_id: int
    source: str
    title: str
    body: str
    severity: str
    created_at: float
    dedupe_key: str
    status: str


class AlertManager:
    """SQLite-backed alert queue with idempotency and digest support."""

    def __init__(self, db_path: str | None = None, notifier: Notifier | None = None):
        configured = db_path or os.getenv("ARIA_ALERT_DB_PATH", "./aria_data/alerts.sqlite3")
        self.db_path = configured
        self.notifier = notifier
        self._lock = asyncio.Lock()
        if configured != ":memory:":
            Path(configured).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL,
                severity TEXT NOT NULL, created_at REAL NOT NULL,
                dedupe_key TEXT NOT NULL UNIQUE, status TEXT NOT NULL,
                delivered_at REAL, last_error TEXT
            )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_alerts_status_severity ON alerts(status, severity, created_at)")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _dedupe(source: str, title: str, body: str, supplied: str | None) -> str:
        if supplied and supplied.strip():
            return supplied.strip()[:512]
        raw = "\0".join((source.strip(), title.strip(), body.strip()))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def enqueue(self, *, source: str, title: str, body: str,
                severity: str = "info", dedupe_key: str | None = None) -> tuple[Alert, bool]:
        source, title, body = (str(v or "").strip() for v in (source, title, body))
        severity = str(severity or "info").strip().lower()
        if not source or not title or not body:
            raise ValueError("source, title and body are required")
        if severity not in VALID_SEVERITIES:
            raise ValueError(f"severity must be one of {sorted(VALID_SEVERITIES)}")
        key = self._dedupe(source, title, body, dedupe_key)
        now = time.time()
        status = "pending_immediate" if severity == "urgent" else "pending_digest"
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO alerts(source,title,body,severity,created_at,dedupe_key,status) VALUES(?,?,?,?,?,?,?)",
                (source, title, body, severity, now, key, status),
            )
            created = cursor.rowcount == 1
            row = conn.execute("SELECT * FROM alerts WHERE dedupe_key=?", (key,)).fetchone()
        return self._to_alert(row), created

    async def enqueue_and_dispatch(self, **kwargs: Any) -> tuple[Alert, bool, bool | None]:
        alert, created = self.enqueue(**kwargs)
        if not created or alert.severity != "urgent":
            return alert, created, None
        delivered = await self.dispatch_urgent(alert.alert_id)
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM alerts WHERE id=?", (alert.alert_id,)).fetchone()
        return self._to_alert(row), created, delivered

    async def dispatch_urgent(self, alert_id: int) -> bool:
        if self.notifier is None:
            return False
        async with self._lock:
            with self._connect() as conn:
                row = conn.execute("SELECT * FROM alerts WHERE id=?", (alert_id,)).fetchone()
                if row is None or row["status"] != "pending_immediate":
                    return bool(row and row["status"] == "delivered")
            message = self._format(row)
            try:
                delivered = bool(await self.notifier(message))
                error = None if delivered else "Notifier returned false"
            except Exception as exc:  # keep alert queued on transient errors
                delivered, error = False, str(exc)[:1000]
            with self._connect() as conn:
                if delivered:
                    conn.execute("UPDATE alerts SET status='delivered', delivered_at=?, last_error=NULL WHERE id=?", (time.time(), alert_id))
                else:
                    conn.execute("UPDATE alerts SET last_error=? WHERE id=?", (error, alert_id))
            return delivered

    def build_digest(self, limit: int = 50) -> tuple[str, list[int]]:
        limit = max(1, min(int(limit), 200))
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM alerts WHERE status='pending_digest' ORDER BY created_at ASC LIMIT ?", (limit,)).fetchall()
        if not rows:
            return "", []
        lines = [f"ARIA digest — {len(rows)} update(s)"]
        for row in rows:
            lines.append(f"\n[{row['severity'].upper()}] {row['source']}: {row['title']}\n{row['body']}")
        return "\n".join(lines)[:3900], [int(row["id"]) for row in rows]

    async def send_digest(self) -> dict[str, Any]:
        message, ids = self.build_digest()
        if not ids:
            return {"sent": False, "reason": "empty", "count": 0}
        if self.notifier is None:
            return {"sent": False, "reason": "notifier_not_configured", "count": len(ids)}
        try:
            delivered = bool(await self.notifier(message))
        except Exception:
            delivered = False
        if delivered:
            placeholders = ",".join("?" for _ in ids)
            with self._connect() as conn:
                conn.execute(f"UPDATE alerts SET status='delivered', delivered_at=?, last_error=NULL WHERE id IN ({placeholders}) AND status='pending_digest'", [time.time(), *ids])
        return {"sent": delivered, "reason": "sent" if delivered else "delivery_failed", "count": len(ids)}

    def pending_count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM alerts WHERE status IN ('pending_immediate','pending_digest')").fetchone()
        return int(row["n"])

    @staticmethod
    def _format(row: sqlite3.Row) -> str:
        return f"ARIA URGENT ALERT\nSource: {row['source']}\n{row['title']}\n\n{row['body']}"[:3900]

    @staticmethod
    def _to_alert(row: sqlite3.Row) -> Alert:
        return Alert(int(row["id"]), row["source"], row["title"], row["body"], row["severity"], float(row["created_at"]), row["dedupe_key"], row["status"])
