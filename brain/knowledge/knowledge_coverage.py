"""Read-only topic coverage audit and safe batch planner for ARIA knowledge.

Examples:
  python -m brain.knowledge.knowledge_coverage --db data/aria_open_knowledge.sqlite3
  python -m brain.knowledge.knowledge_coverage --db data/aria_open_knowledge.sqlite3 --batch-size 50 --batch 1
  python -m brain.knowledge.knowledge_coverage --db data/aria_open_knowledge.sqlite3 --batch-size 50 --plan-out data/knowledge_batch_plan.json

This module never creates or changes the knowledge database. Topic matching is
conservative: it matches normalized catalog titles to stored Wikipedia titles.
It does not claim semantic coverage merely because a related article exists.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

from brain.knowledge.open_knowledge import DEFAULT_DB, read_topics_file

DEFAULT_TOPICS_FILE = Path(__file__).with_name("core_topics.txt")


def normalize_title(value: str) -> str:
    """Normalize case and punctuation for conservative title matching."""
    value = str(value or "").casefold().strip()
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"[_-]+", " ", value)
    value = re.sub(r"[^\w ]", "", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()


def load_wikipedia_titles(db_path: str | Path) -> set[str]:
    """Read stored Wikipedia titles without creating or modifying the DB."""
    path = Path(db_path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"Knowledge database does not exist: {path}")
    if not path.is_file():
        raise ValueError(f"Knowledge database path is not a file: {path}")
    uri = path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=10)
    try:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "documents" not in tables:
            raise ValueError("Database has no 'documents' table")
        columns = {row[1] for row in conn.execute("PRAGMA table_info(documents)")}
        if not {"source", "title"}.issubset(columns):
            raise ValueError("Documents table must contain source and title columns")
        return {
            normalize_title(row[0])
            for row in conn.execute(
                "SELECT title FROM documents WHERE LOWER(source) = 'wikipedia'"
            )
            if normalize_title(row[0])
        }
    finally:
        conn.close()


def build_coverage_report(
    topics_file: str | Path = DEFAULT_TOPICS_FILE,
    db_path: str | Path = DEFAULT_DB,
    batch_size: int = 50,
    batch_number: int = 1,
) -> dict[str, Any]:
    """Audit exact/normalized title coverage and produce a deterministic batch."""
    if batch_size < 1 or batch_size > 500:
        raise ValueError("batch_size must be between 1 and 500")
    if batch_number < 1:
        raise ValueError("batch_number must be 1 or greater")

    topics_path = Path(topics_file).expanduser()
    if not topics_path.is_file():
        raise FileNotFoundError(f"Topics file not found: {topics_path}")
    raw_topics = read_topics_file(str(topics_path))
    topics: list[str] = []
    seen: set[str] = set()
    for raw in raw_topics:
        topic = str(raw).strip()
        key = normalize_title(topic)
        if topic and key and key not in seen:
            topics.append(topic)
            seen.add(key)

    stored_titles = load_wikipedia_titles(db_path)
    covered = [topic for topic in topics if normalize_title(topic) in stored_titles]
    missing = [topic for topic in topics if normalize_title(topic) not in stored_titles]
    total_batches = (len(missing) + batch_size - 1) // batch_size
    start = (batch_number - 1) * batch_size
    batch_topics = missing[start:start + batch_size]

    return {
        "status": "ok",
        "read_only": True,
        "topics_file": str(topics_path.resolve()),
        "database": str(Path(db_path).expanduser().resolve()),
        "matching_method": "normalized Wikipedia title match only; related/semantic coverage is not inferred",
        "catalog_topics": len(topics),
        "duplicate_catalog_entries_removed": len(raw_topics) - len(topics),
        "stored_wikipedia_titles": len(stored_titles),
        "covered_topics": len(covered),
        "missing_topics": len(missing),
        "coverage_percent": round((len(covered) / len(topics) * 100), 2) if topics else 100.0,
        "batch_size": batch_size,
        "requested_batch": batch_number,
        "total_missing_batches": total_batches,
        "batch_count": len(batch_topics),
        "batch_topics": batch_topics,
        "next_batch": batch_number + 1 if start + batch_size < len(missing) else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit ARIA knowledge topic coverage and plan bounded batches")
    parser.add_argument("--db", default=DEFAULT_DB, help="Existing ARIA knowledge SQLite database")
    parser.add_argument("--topics-file", default=str(DEFAULT_TOPICS_FILE), help="One topic per line; comment lines start with #")
    parser.add_argument("--batch-size", type=int, default=50, help="Topics per planned batch (1-500)")
    parser.add_argument("--batch", type=int, default=1, help="1-based missing-topic batch to display")
    parser.add_argument("--plan-out", help="Optional path to write this JSON report; database remains read-only")
    args = parser.parse_args(argv)
    try:
        report = build_coverage_report(args.topics_file, args.db, args.batch_size, args.batch)
        rendered = json.dumps(report, ensure_ascii=False, indent=2)
        if args.plan_out:
            output = Path(args.plan_out).expanduser()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(rendered + "\n", encoding="utf-8")
        print(rendered)
        return 0
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"ARIA knowledge coverage audit failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
