"""Approval-gated, persistent workflow for ARIA briefings.

This module deliberately does not fetch provider data and does not expose HTTP
routes. The caller must collect data through already-authorized read-only
adapters, protect the approval endpoint with ARIA's owner authentication, and
pass owner_approved=True only after that authorization check succeeds.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable, Mapping

from integrations.briefing_engine import build_briefing

Notifier = Callable[[str], Awaitable[bool]]


class BriefingWorkflow:
    """Store previews and send only after an explicit owner approval."""

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or os.getenv("ARIA_ALERT_DB_PATH", "./aria_data/alerts.sqlite3")
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS briefing_previews (
                briefing_id TEXT PRIMARY KEY,
                period TEXT NOT NULL,
                generated_at TEXT NOT NULL,
                body TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at REAL NOT NULL,
                approved_at REAL,
                delivered_at REAL,
                last_error TEXT
            )""")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def prepare(self, items: Iterable[Mapping[str, Any]], *, period: str = "daily") -> dict[str, Any]:
        """Build and persist a preview; this method never sends a message."""
        result = build_briefing(items, period=period)
        briefing_id = uuid.uuid4().hex
        metadata = {k: v for k, v in result.items() if k != "text"}
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO briefing_previews(briefing_id,period,generated_at,body,metadata_json,status,created_at) VALUES(?,?,?,?,?,?,?)",
                (briefing_id, result["period"], result["generated_at"], result["text"], json.dumps(metadata, ensure_ascii=False), "pending_approval", time.time()),
            )
        return {
            "briefing_id": briefing_id,
            "status": "pending_approval",
            "text": result["text"],
            "metadata": metadata,
            "requires_owner_approval": True,
            "sent": False,
        }

    def get_preview(self, briefing_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM briefing_previews WHERE briefing_id=?", (briefing_id,)).fetchone()
        if row is None:
            return None
        return {
            "briefing_id": row["briefing_id"],
            "period": row["period"],
            "generated_at": row["generated_at"],
            "text": row["body"],
            "metadata": json.loads(row["metadata_json"]),
            "status": row["status"],
            "requires_owner_approval": row["status"] == "pending_approval",
        }

    async def approve_and_send(
        self,
        briefing_id: str,
        *,
        owner_approved: bool,
        notifier: Notifier,
    ) -> dict[str, Any]:
        """Send once only when caller confirms the authenticated owner's approval.

        IMPORTANT: `owner_approved` must be set by a protected route after
        validating the real owner/session; never trust a user-supplied JSON flag.
        """
        if owner_approved is not True:
            return {"sent": False, "status": "approval_required", "reason": "owner_approval_required"}
        if not callable(notifier):
            return {"sent": False, "status": "pending_approval", "reason": "notifier_not_configured"}

        # Claim the item atomically before sending to avoid duplicate concurrent
        # approvals. If delivery fails, restore pending_approval for a retry.
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM briefing_previews WHERE briefing_id=?", (briefing_id,)).fetchone()
            if row is None:
                conn.rollback()
                return {"sent": False, "status": "not_found", "reason": "unknown_briefing_id"}
            if row["status"] == "delivered":
                conn.commit()
                return {"sent": True, "status": "delivered", "reason": "already_delivered"}
            if row["status"] != "pending_approval":
                conn.commit()
                return {"sent": False, "status": row["status"], "reason": "not_awaiting_approval"}
            conn.execute("UPDATE briefing_previews SET status='sending', approved_at=?, last_error=NULL WHERE briefing_id=?", (time.time(), briefing_id))
            body = row["body"]
            conn.commit()

        try:
            delivered = bool(await notifier(body[:3900]))
            error = None if delivered else "Notifier returned false"
        except Exception as exc:
            delivered = False
            error = str(exc)[:500]

        with self._connect() as conn:
            if delivered:
                conn.execute("UPDATE briefing_previews SET status='delivered', delivered_at=?, last_error=NULL WHERE briefing_id=? AND status='sending'", (time.time(), briefing_id))
            else:
                conn.execute("UPDATE briefing_previews SET status='pending_approval', last_error=? WHERE briefing_id=? AND status='sending'", (error, briefing_id))
        return {"sent": delivered, "status": "delivered" if delivered else "pending_approval", "reason": "sent" if delivered else "delivery_failed"}
