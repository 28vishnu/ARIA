"""Read-only-by-default freshness audit and controlled review scheduling for ARIA docs.

This module does not fetch or rewrite source content. It classifies existing documents by
import time and optional review metadata, and can initialize/update its own review table
only when explicitly requested with --execute.
"""
from __future__ import annotations
import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DEFAULT_MAX_AGE_DAYS = 180
FRESHNESS_TABLE = "aria_document_freshness"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _read_documents(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "documents" not in tables:
        raise RuntimeError("Database has no 'documents' table; use ARIA's existing knowledge database")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(documents)")}
    required = {"id", "source", "source_id", "title", "url", "imported_at"}
    if not required.issubset(cols):
        raise RuntimeError("The 'documents' table is missing expected ARIA columns")
    rows = conn.execute("SELECT id, source, source_id, title, url, imported_at FROM documents ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def audit_freshness(db_path: str | Path, max_age_days: int = DEFAULT_MAX_AGE_DAYS,
                    now: datetime | None = None) -> dict[str, Any]:
    """Audit document age without creating tables or modifying the database."""
    if max_age_days < 1:
        raise ValueError("max_age_days must be at least 1")
    db = Path(db_path).expanduser().resolve()
    if not db.is_file():
        raise FileNotFoundError(f"Database does not exist: {db}; no database was created")
    current = (now or _utc_now()).astimezone(timezone.utc)
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        docs = _read_documents(conn)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        review: dict[int, dict[str, Any]] = {}
        if FRESHNESS_TABLE in tables:
            for r in conn.execute(f"SELECT document_id, max_age_days, last_reviewed_at, next_review_at, review_status FROM {FRESHNESS_TABLE}"):
                review[int(r[0])] = {"max_age_days": r[1], "last_reviewed_at": r[2],
                                     "next_review_at": r[3], "review_status": r[4]}
        output = []
        counts = {"fresh": 0, "stale": 0, "unknown": 0, "review_due": 0}
        for doc in docs:
            imported = _parse_datetime(doc.get("imported_at"))
            metadata = review.get(int(doc["id"]), {})
            age_limit = int(metadata.get("max_age_days") or max_age_days)
            age_days = max(0, (current - imported).days) if imported else None
            if imported is None:
                status = "unknown"
            elif age_days > age_limit:
                status = "stale"
            else:
                status = "fresh"
            next_review = _parse_datetime(metadata.get("next_review_at"))
            due = bool(next_review and next_review <= current)
            counts[status] += 1
            counts["review_due"] += int(due)
            output.append({"id": doc["id"], "source": doc["source"], "source_id": doc["source_id"],
                           "title": doc["title"], "url": doc["url"], "imported_at": doc["imported_at"],
                           "age_days": age_days, "max_age_days": age_limit, "freshness": status,
                           "next_review_at": metadata.get("next_review_at"), "review_due": due,
                           "review_status": metadata.get("review_status", "unreviewed")})
        return {"status": "audit", "database": str(db), "checked_at": current.isoformat(),
                "default_max_age_days": max_age_days, "total_documents": len(output), "counts": counts,
                "documents": output}
    finally:
        conn.close()


def schedule_reviews(db_path: str | Path, max_age_days: int = DEFAULT_MAX_AGE_DAYS,
                     review_interval_days: int = 90, execute: bool = False,
                     now: datetime | None = None) -> dict[str, Any]:
    """Plan or persist review dates. Writes only to ARIA's dedicated metadata table."""
    if max_age_days < 1 or review_interval_days < 1:
        raise ValueError("max_age_days and review_interval_days must be at least 1")
    db = Path(db_path).expanduser().resolve()
    if not db.is_file():
        raise FileNotFoundError(f"Database does not exist: {db}; no database was created")
    current = (now or _utc_now()).astimezone(timezone.utc)
    # Audit is strictly read-only; it also validates the expected database schema.
    audit = audit_freshness(db, max_age_days=max_age_days, now=current)
    planned = [{"document_id": d["id"], "next_review_at": (current + timedelta(days=review_interval_days)).isoformat(),
                "max_age_days": max_age_days} for d in audit["documents"]]
    report = {"status": "preview", "execute_requested": execute, "database": str(db),
              "documents_considered": len(planned), "review_interval_days": review_interval_days,
              "planned": planned}
    if not execute:
        return report
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=rw", uri=True, timeout=15)
    try:
        conn.execute(f"""CREATE TABLE IF NOT EXISTS {FRESHNESS_TABLE} (
            document_id INTEGER PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
            max_age_days INTEGER NOT NULL,
            last_reviewed_at TEXT,
            next_review_at TEXT NOT NULL,
            review_status TEXT NOT NULL DEFAULT 'scheduled',
            updated_at TEXT NOT NULL
        )""")
        with conn:
            for item in planned:
                conn.execute(f"""INSERT INTO {FRESHNESS_TABLE}
                    (document_id, max_age_days, next_review_at, review_status, updated_at)
                    VALUES (?, ?, ?, 'scheduled', ?)
                    ON CONFLICT(document_id) DO UPDATE SET
                      max_age_days=excluded.max_age_days,
                      next_review_at=excluded.next_review_at,
                      review_status=CASE WHEN {FRESHNESS_TABLE}.review_status='verified' THEN 'verified' ELSE 'scheduled' END,
                      updated_at=excluded.updated_at""",
                    (item["document_id"], item["max_age_days"], item["next_review_at"], current.isoformat()))
        report["status"] = "scheduled"
        report["scheduled_count"] = len(planned)
        return report
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit ARIA knowledge freshness and plan review dates")
    parser.add_argument("--db", required=True, help="Path to an existing ARIA SQLite knowledge database")
    parser.add_argument("--max-age-days", type=int, default=DEFAULT_MAX_AGE_DAYS)
    parser.add_argument("--schedule-reviews", action="store_true", help="Plan review dates instead of auditing only")
    parser.add_argument("--review-interval-days", type=int, default=90)
    parser.add_argument("--execute", action="store_true", help="Persist review schedule; default is read-only preview")
    args = parser.parse_args(argv)
    try:
        if args.schedule_reviews:
            result = schedule_reviews(args.db, args.max_age_days, args.review_interval_days, args.execute)
        else:
            if args.execute:
                parser.error("--execute is only valid with --schedule-reviews")
            result = audit_freshness(args.db, args.max_age_days)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (OSError, ValueError, sqlite3.Error, RuntimeError) as exc:
        print(f"ARIA knowledge freshness failed: {exc}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
