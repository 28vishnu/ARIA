"""Read-only unified integration status endpoint for ARIA.

Reports configuration and local token-record presence only. It does not call
external providers, expose secrets, or mutate user data.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter

router = APIRouter(tags=["ARIA JARVIS status"])


def _db_path() -> str:
    return (os.getenv("ARIA_ALERT_DB_PATH") or "./aria_data/alerts.sqlite3").strip()


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", (table,)
    ).fetchone()
    return row is not None


def build_status(db_path: str | None = None, env: dict[str, str] | None = None) -> dict[str, Any]:
    """Build a safe status summary; injectable arguments make this testable."""
    environ = env if env is not None else os.environ
    path = db_path if db_path is not None else (environ.get("ARIA_ALERT_DB_PATH") or "./aria_data/alerts.sqlite3")
    result: dict[str, Any] = {
        "service": "ARIA JARVIS integrations",
        "database": {"configured": bool(path), "exists": Path(path).exists() if path != ":memory:" else True},
        "integrations": {
            "telegram_notifications": {"configured": bool((environ.get("TELEGRAM_BOT_TOKEN") or environ.get("TELEGRAM_TOKEN")) and (environ.get("ADMIN_CHAT_ID") or environ.get("TELEGRAM_CHAT_ID")))},
            "github_webhook": {"configured": bool(environ.get("GITHUB_WEBHOOK_SECRET"))},
            "gmail_readonly": {"connected": False, "scope": "read-only"},
            "google_calendar_readonly": {"connected": False, "scope": "read-only"},
            "google_drive_readonly": {"connected": False, "scope": "read-only"},
        },
        "alerts": {"pending_urgent": None, "pending_digest": None},
        "notes": [
            "Connected means an encrypted token record exists locally; it does not prove the provider token is currently valid.",
            "This endpoint never returns tokens, OAuth secrets, webhook secrets, email contents, or file contents.",
        ],
    }
    if path == ":memory:" or Path(path).exists():
        try:
            conn = sqlite3.connect(path, timeout=3)
            conn.row_factory = sqlite3.Row
            try:
                tables = {
                    name: _table_exists(conn, name)
                    for name in ("gmail_oauth_tokens", "calendar_oauth_tokens", "drive_oauth_tokens", "alerts")
                }
                result["database"]["readable"] = True
                for key, table in (("gmail_readonly", "gmail_oauth_tokens"), ("google_calendar_readonly", "calendar_oauth_tokens"), ("google_drive_readonly", "drive_oauth_tokens")):
                    if tables[table]:
                        row = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
                        result["integrations"][key]["connected"] = int(row["n"]) > 0
                    else:
                        result["integrations"][key]["token_store_initialized"] = False
                if tables["alerts"]:
                    rows = conn.execute("SELECT status, COUNT(*) AS n FROM alerts GROUP BY status").fetchall()
                    counts = {row["status"]: int(row["n"]) for row in rows}
                    result["alerts"]["pending_urgent"] = counts.get("pending_immediate", 0)
                    result["alerts"]["pending_digest"] = counts.get("pending_digest", 0)
                else:
                    result["alerts"]["pending_urgent"] = 0
                    result["alerts"]["pending_digest"] = 0
            finally:
                conn.close()
        except (sqlite3.Error, OSError):
            result["database"]["readable"] = False
    else:
        result["database"]["readable"] = False
    return result


@router.get("/jarvis/status")
def jarvis_status():
    """Owner-authenticated by default under ARIA's existing auth middleware."""
    return build_status()
