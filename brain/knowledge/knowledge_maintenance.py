"""Controlled maintenance commands for ARIA's persistent local knowledge corpus.

Run ingestion as a deliberate Render Shell/one-off task, not on every web request.
Examples:
  python -m brain.knowledge.knowledge_maintenance status
  python -m brain.knowledge.knowledge_maintenance bootstrap --seed-limit 120 --news
  python -m brain.knowledge.knowledge_maintenance bootstrap --seed-limit 0 --news

Set ARIA_OPEN_KNOWLEDGE_DB to the persistent database path before running.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any

from brain.knowledge.open_knowledge import (
    DEFAULT_DB, DEFAULT_SEED_TOPICS, connect, read_topics_file, seed_topics,
)

LOG = logging.getLogger("aria.knowledge_maintenance")
DEFAULT_TOPICS_FILE = Path(__file__).with_name("core_topics.txt")


def database_status(db_path: str = DEFAULT_DB) -> dict[str, Any]:
    """Report actual corpus coverage and index capability without changing data."""
    conn = connect(db_path)
    try:
        total = int(conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0])
        by_source = {
            str(row[0]): int(row[1])
            for row in conn.execute(
                "SELECT source, COUNT(*) FROM documents GROUP BY source ORDER BY source"
            )
        }
        licensed = int(conn.execute(
            "SELECT COUNT(*) FROM documents WHERE license IS NOT NULL AND license != '' AND license != 'unknown'"
        ).fetchone()[0])
        with_urls = int(conn.execute(
            "SELECT COUNT(*) FROM documents WHERE url LIKE 'http://%' OR url LIKE 'https://%'"
        ).fetchone()[0])
        tables = {str(row[0]) for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        fts5 = "documents_fts" in tables
        return {
            "status": "ok",
            "database": str(Path(db_path).expanduser().resolve()),
            "total_documents": total,
            "documents_by_source": by_source,
            "records_with_license_metadata": licensed,
            "records_with_source_urls": with_urls,
            "fts5_available": fts5,
        }
    finally:
        conn.close()


def bootstrap(
    db_path: str = DEFAULT_DB,
    topics_file: str | None = str(DEFAULT_TOPICS_FILE),
    seed_limit: int = 120,
    delay: float = 0.2,
    timeout: int = 6,
    collect_news: bool = False,
) -> dict[str, Any]:
    """Seed a bounded starter corpus and optionally collect recent RSS items.

    This is intentionally a one-off maintenance operation. It does not download
    full Wikipedia/Wikidata dumps or silently ingest datasets with restrictive
    licenses. Repeated runs are idempotent for existing Wikipedia titles.
    """
    if seed_limit < 0:
        raise ValueError("seed_limit must be zero or greater")
    if timeout < 1 or timeout > 60:
        raise ValueError("timeout must be between 1 and 60 seconds")
    if delay < 0 or delay > 5:
        raise ValueError("delay must be between 0 and 5 seconds")

    topics = list(DEFAULT_SEED_TOPICS)
    if topics_file:
        path = Path(topics_file).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"Topics file not found: {path}")
        topics = read_topics_file(str(path))

    result: dict[str, Any] = {
        "status": "completed",
        "database_before": database_status(db_path),
        "seed": None,
        "news": None,
    }
    if seed_limit > 0:
        # seed_topics combines caller topics with its built-in starter topics.
        result["seed"] = seed_topics(
            db_path=db_path,
            topics=topics,
            delay=delay,
            timeout=timeout,
            limit=seed_limit,
        )
    if collect_news:
        from brain.knowledge.knowledge_hub import collect_news_and_updates
        result["news"] = collect_news_and_updates(force=True, db_path=db_path)
    result["database_after"] = database_status(db_path)
    LOG.info(
        "Knowledge maintenance complete: documents=%d sources=%d",
        result["database_after"]["total_documents"],
        len(result["database_after"]["documents_by_source"]),
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ARIA controlled knowledge maintenance")
    parser.add_argument("--db", default=os.environ.get("ARIA_OPEN_KNOWLEDGE_DB", DEFAULT_DB))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="Show actual corpus counts and provenance coverage")
    run = sub.add_parser("bootstrap", help="Seed a bounded starter corpus and optionally refresh RSS")
    run.add_argument("--topics-file", default=str(DEFAULT_TOPICS_FILE))
    run.add_argument("--seed-limit", type=int, default=120)
    run.add_argument("--delay", type=float, default=0.2)
    run.add_argument("--timeout", type=int, default=6)
    run.add_argument("--news", action="store_true", help="Collect current RSS items after seeding")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        if args.command == "status":
            result = database_status(args.db)
        else:
            result = bootstrap(
                db_path=args.db,
                topics_file=args.topics_file,
                seed_limit=args.seed_limit,
                delay=args.delay,
                timeout=args.timeout,
                collect_news=args.news,
            )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, sqlite3.Error, RuntimeError) as exc:
        LOG.error("Knowledge maintenance failed: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
