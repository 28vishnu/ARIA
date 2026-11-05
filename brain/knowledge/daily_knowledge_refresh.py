"""Auditable, bounded daily refresh orchestration for ARIA's local knowledge corpus.

Preview is read-only and performs no network requests:
    python -m brain.knowledge.daily_knowledge_refresh --db /var/data/aria_open_knowledge.sqlite3

Execute one daily refresh deliberately:
    python -m brain.knowledge.daily_knowledge_refresh --db /var/data/aria_open_knowledge.sqlite3 --execute

Configure a Render Cron Job to run the execute command once per day. The module
never claims to contain all world knowledge; it reports source coverage, feed
outcomes, document freshness, and partial failures explicitly.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from brain.knowledge.knowledge_freshness import audit_freshness
from brain.knowledge.knowledge_hub import _feed_list, collect_news_and_updates
from brain.knowledge.source_registry import load_registry

RUNS_TABLE = "aria_daily_refresh_runs"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _open_existing_db(db_path: str | Path, *, readonly: bool) -> sqlite3.Connection:
    path = Path(db_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Knowledge database does not exist: {path}; no database was created")
    if readonly:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=10)
    else:
        conn = sqlite3.connect(str(path), timeout=15)
        conn.execute("PRAGMA busy_timeout=15000")
    conn.row_factory = sqlite3.Row
    tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "documents" not in tables:
        conn.close()
        raise RuntimeError("Knowledge database has no 'documents' table")
    return conn


def _latest_success_for_day(conn: sqlite3.Connection, day: str) -> dict[str, Any] | None:
    tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if RUNS_TABLE not in tables:
        return None
    row = conn.execute(
        f"SELECT run_id, started_at, finished_at, status, report_json FROM {RUNS_TABLE} "
        "WHERE utc_day=? AND status IN ('ok','partial') ORDER BY id DESC LIMIT 1",
        (day,),
    ).fetchone()
    if not row:
        return None
    try:
        report = json.loads(row["report_json"])
    except (TypeError, json.JSONDecodeError):
        report = {}
    return {"run_id": row["run_id"], "started_at": row["started_at"],
            "finished_at": row["finished_at"], "status": row["status"], "report": report}


def _ensure_runs_table(conn: sqlite3.Connection) -> None:
    conn.execute(f"""CREATE TABLE IF NOT EXISTS {RUNS_TABLE} (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL UNIQUE,
        utc_day TEXT NOT NULL,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        status TEXT NOT NULL,
        report_json TEXT NOT NULL
    )""")
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{RUNS_TABLE}_day ON {RUNS_TABLE}(utc_day, status)")
    conn.commit()


def _registry_summary() -> dict[str, Any]:
    registry = load_registry()
    sources = registry["sources"]
    return {
        "schema_version": registry["schema_version"],
        "registered_source_count": len(sources),
        "sources": sorted(sources.keys()),
        "unreviewed_redistribution_sources": sorted(
            name for name, entry in sources.items()
            if entry.get("redistribution_review_required")
        ),
        "commercial_use_review_sources": sorted(
            name for name, entry in sources.items()
            if entry.get("commercial_use_review_required")
        ),
    }


def run_daily_refresh(
    db_path: str | Path,
    *,
    execute: bool = False,
    force: bool = False,
    max_age_days: int = 180,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Create a read-only preview or execute one auditable daily refresh.

    Execution collects configured RSS feeds, audits freshness, and persists a
    compact run report. It does not download large dumps or silently import
    unrestricted datasets.
    """
    if max_age_days < 1:
        raise ValueError("max_age_days must be at least 1")
    current = now or _utc_now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc).replace(microsecond=0)
    started_at = current.isoformat()
    utc_day = current.date().isoformat()
    db = Path(db_path).expanduser().resolve()

    # Read-only preflight: no table creation and no network requests.
    conn = _open_existing_db(db, readonly=not execute)
    try:
        prior = _latest_success_for_day(conn, utc_day)
        doc_count = int(conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0])
        source_rows = conn.execute(
            "SELECT source, COUNT(*) AS n FROM documents GROUP BY source ORDER BY source"
        ).fetchall()
        source_counts = {str(row["source"]): int(row["n"]) for row in source_rows}
    finally:
        conn.close()

    registry = _registry_summary()
    feed_names = [name for name, _ in _feed_list()]
    freshness = audit_freshness(db, max_age_days=max_age_days, now=current)
    base: dict[str, Any] = {
        "status": "preview", "execute_requested": bool(execute), "database": str(db),
        "started_at": started_at, "utc_day": utc_day, "idempotency": "daily-utc",
        "document_count_before": doc_count, "documents_by_source_before": source_counts,
        "source_registry": registry, "configured_feed_names": feed_names,
        "freshness_before": {"total_documents": freshness["total_documents"],
                              "counts": freshness["counts"]},
        "refresh": None,
    }
    if not execute:
        base["network_requested"] = False
        base["database_writes_requested"] = False
        return base

    # The second check occurs after opening writable DB and creating the run table,
    # so overlapping cron executions can safely skip an already successful day.
    conn = _open_existing_db(db, readonly=False)
    try:
        _ensure_runs_table(conn)
        # Serialize the idempotency check and run registration so overlapping
        # cron invocations do not both begin the same daily refresh.
        conn.execute("BEGIN IMMEDIATE")
        current_prior = _latest_success_for_day(conn, utc_day)
        if current_prior and not force:
            conn.rollback()
            base.update({"status": "already_refreshed_today", "skipped": True,
                         "previous_run": current_prior, "network_requested": False})
            return base
        import uuid
        run_id = uuid.uuid4().hex
        conn.execute(
            f"INSERT INTO {RUNS_TABLE}(run_id,utc_day,started_at,status,report_json) VALUES(?,?,?,'running',?)",
            (run_id, utc_day, started_at, json.dumps({"status": "running"})),
        )
        conn.commit()
    finally:
        conn.close()

    refresh_result: dict[str, Any]
    try:
        refresh_result = collect_news_and_updates(force=True, db_path=str(db))
        feed_results = refresh_result.get("feeds", []) if isinstance(refresh_result, dict) else []
        failed = sum(1 for item in feed_results if item.get("status") != "ok")
        status = "partial" if failed else "ok"
        refresh_error = None
    except Exception as exc:
        # Store exception type and a bounded message, but do not include source URLs
        # or configuration values in the report.
        refresh_result = {"feeds_checked": 0, "items_seen": 0, "feeds": []}
        failed = len(feed_names)
        status = "error"
        refresh_error = f"{type(exc).__name__}: {str(exc)[:240]}"

    finished_at = _utc_now().isoformat()
    after = audit_freshness(db, max_age_days=max_age_days)
    conn = _open_existing_db(db, readonly=False)
    try:
        report_to_store = {
            "status": status, "feeds_checked": int(refresh_result.get("feeds_checked", 0)),
            "items_seen": int(refresh_result.get("items_seen", 0)),
            "failed_feeds": int(failed), "error": refresh_error,
            "document_count_before": doc_count, "freshness_after": after["counts"],
        }
        conn.execute(
            f"UPDATE {RUNS_TABLE} SET finished_at=?, status=?, report_json=? WHERE run_id=?",
            (finished_at, status, json.dumps(report_to_store, ensure_ascii=False), run_id),
        )
        conn.commit()
        final_count = int(conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0])
    finally:
        conn.close()

    base.update({
        "status": status, "network_requested": True, "database_writes_requested": True,
        "run_id": run_id, "finished_at": finished_at, "document_count_after": final_count,
        "documents_added_net": final_count - doc_count,
        "freshness_after": {"total_documents": after["total_documents"], "counts": after["counts"]},
        "refresh": refresh_result, "failed_feed_count": int(failed), "error": refresh_error,
    })
    return base


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Preview or run ARIA's auditable daily knowledge refresh")
    parser.add_argument("--db", default=os.environ.get("ARIA_OPEN_KNOWLEDGE_DB", "data/aria_open_knowledge.sqlite3"))
    parser.add_argument("--execute", action="store_true", help="Fetch configured RSS feeds and persist a run report")
    parser.add_argument("--force", action="store_true", help="Allow a second successful refresh on the same UTC day")
    parser.add_argument("--max-age-days", type=int, default=180)
    args = parser.parse_args(argv)
    try:
        report = run_daily_refresh(args.db, execute=args.execute, force=args.force,
                                   max_age_days=args.max_age_days)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report.get("status") in {"preview", "ok", "partial", "already_refreshed_today"} else 1
    except (OSError, ValueError, sqlite3.Error, RuntimeError) as exc:
        print(f"ARIA daily knowledge refresh failed: {type(exc).__name__}: {str(exc)[:300]}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
