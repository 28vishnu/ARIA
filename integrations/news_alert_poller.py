"""Turn newly acquired local RSS headlines into persistent ARIA alerts.

The poller reads only ARIA's already-ingested local news corpus. It does not
fetch feeds itself, does not summarize with an LLM, and deduplicates headlines
across restarts. Ordinary items enter the next digest; selected high-risk
security advisories are delivered immediately through AlertManager.
"""
from __future__ import annotations

import logging
import os
import re
import sqlite3
from pathlib import Path
from typing import Any

from integrations.alert_manager import AlertManager

_LOG = logging.getLogger("aria.news_alerts")
_URGENT_TITLE = re.compile(
    r"\b(?:actively exploited|zero[- ]day|critical vulnerability|security breach|"
    r"ransomware|massive data breach|emergency security update)\b",
    re.IGNORECASE,
)


class NewsAlertPoller:
    """Queue fresh headlines from the local knowledge database for notification."""

    def __init__(
        self,
        manager: AlertManager,
        *,
        knowledge_db_path: str | None = None,
        batch_size: int = 40,
    ) -> None:
        self.manager = manager
        self.knowledge_db_path = knowledge_db_path or os.getenv(
            "ARIA_OPEN_KNOWLEDGE_DB", "data/aria_open_knowledge.sqlite3"
        )
        self.batch_size = max(1, min(int(batch_size), 200))
        with self.manager._connect() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS news_alert_seen (
                    source_id TEXT PRIMARY KEY,
                    first_seen REAL NOT NULL
                )"""
            )

    def _fetch_latest(self) -> list[dict[str, Any]]:
        path = Path(self.knowledge_db_path).expanduser()
        if not path.is_file():
            return []
        try:
            with sqlite3.connect(str(path), timeout=10) as conn:
                conn.row_factory = sqlite3.Row
                columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(documents)")}
                required = {"source", "source_id", "title", "content", "url", "imported_at"}
                if not required.issubset(columns):
                    _LOG.warning("Local news corpus has an unexpected documents schema; skipping alerts.")
                    return []
                rows = conn.execute(
                    "SELECT source_id,title,content,url,imported_at FROM documents "
                    "WHERE source='news' AND imported_at >= datetime('now','-2 days') "
                    "ORDER BY imported_at DESC, id DESC LIMIT ?",
                    (self.batch_size,),
                ).fetchall()
                return [dict(row) for row in rows]
        except (sqlite3.Error, OSError):
            _LOG.exception("Could not read local news corpus for alerting.")
            return []

    async def tick(self) -> dict[str, int]:
        """Queue newly seen items; send only clearly urgent security headlines now."""
        rows = self._fetch_latest()
        queued = urgent = duplicates = 0
        for row in reversed(rows):
            source_id = str(row.get("source_id") or "").strip()
            title = str(row.get("title") or "").strip()
            if not source_id or not title:
                continue
            with self.manager._connect() as conn:
                exists = conn.execute(
                    "SELECT 1 FROM news_alert_seen WHERE source_id=?", (source_id,)
                ).fetchone()
            if exists:
                duplicates += 1
                continue
            raw_content = str(row.get("content") or "").strip()
            summary = re.sub(r"(?im)^Published:\s*.*$", "", raw_content)
            summary = re.sub(r"(?im)^Feed:\s*.*$", "", summary)
            summary = re.sub(r"(?im)^Headline:\s*.*$", "", summary)
            summary = re.sub(r"(?im)^Summary:\s*", "", summary).strip()
            url = str(row.get("url") or "").strip()
            body = (summary[:900] if summary else "New headline acquired by ARIA.")
            if url.startswith(("https://", "http://")):
                body += f"\nSource: {url}"
            severity = "urgent" if _URGENT_TITLE.search(title) else "info"
            alert, created, delivered = await self.manager.enqueue_and_dispatch(
                source="news",
                title=title[:400],
                body=body[:1400],
                severity=severity,
                dedupe_key=f"news:{source_id}"[:512],
            )
            with self.manager._connect() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO news_alert_seen(source_id,first_seen) VALUES(?,strftime('%s','now'))",
                    (source_id,),
                )
                # Bound state growth while retaining a generous recent history.
                conn.execute(
                    "DELETE FROM news_alert_seen WHERE first_seen < strftime('%s','now') - 7776000"
                )
            if created:
                queued += 1
                if severity == "urgent":
                    urgent += 1
                    if delivered is False:
                        _LOG.warning("Urgent news alert queued but delivery has not been confirmed: %s", title[:120])
        return {"scanned": len(rows), "queued": queued, "urgent": urgent, "already_seen": duplicates}
