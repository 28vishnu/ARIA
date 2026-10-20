"""Read-only health and coverage reports for ARIA's SQLite knowledge corpus.

Examples:
  python -m brain.knowledge.corpus_status --db data/aria_open_knowledge.sqlite3
  python -m brain.knowledge.corpus_status --db data/aria_open_knowledge.sqlite3 --json
  python -m brain.knowledge.corpus_status --db data/aria_open_knowledge.sqlite3 --check

This module never creates a database, imports records, or changes existing data.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

DEFAULT_DB = os.environ.get("ARIA_OPEN_KNOWLEDGE_DB", "data/aria_open_knowledge.sqlite3")


def inspect_corpus(db_path: str | os.PathLike[str]) -> dict[str, Any]:
    """Return corpus statistics without modifying the database."""
    path = Path(db_path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"Knowledge database does not exist: {path}")
    if not path.is_file():
        raise ValueError(f"Knowledge database path is not a file: {path}")

    # URI read-only mode prevents accidental schema creation or data writes.
    uri = path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "documents" not in tables:
            raise ValueError("Database has no 'documents' table; initialize/import the ARIA knowledge corpus first")
        columns = {row[1] for row in conn.execute("PRAGMA table_info(documents)")}
        required = {"id", "source", "source_id", "title", "content", "url", "imported_at"}
        missing = sorted(required - columns)
        if missing:
            raise ValueError("Documents table is missing required columns: " + ", ".join(missing))

        total = int(conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0])
        by_source = [dict(row) for row in conn.execute(
            "SELECT source, COUNT(*) AS records, MAX(imported_at) AS latest_import "
            "FROM documents GROUP BY source ORDER BY records DESC, source ASC"
        )]
        empty_content = int(conn.execute(
            "SELECT COUNT(*) FROM documents WHERE content IS NULL OR TRIM(content) = ''"
        ).fetchone()[0])
        empty_title = int(conn.execute(
            "SELECT COUNT(*) FROM documents WHERE title IS NULL OR TRIM(title) = ''"
        ).fetchone()[0])
        empty_url = int(conn.execute(
            "SELECT COUNT(*) FROM documents WHERE url IS NULL OR TRIM(url) = ''"
        ).fetchone()[0])
        license_missing = int(conn.execute(
            "SELECT COUNT(*) FROM documents WHERE "
            + ("license IS NULL OR TRIM(license) = '' OR LOWER(TRIM(license)) = 'unknown'" if "license" in columns else "1 = 1")
        ).fetchone()[0])
        duplicate_keys = int(conn.execute(
            "SELECT COUNT(*) FROM (SELECT source, source_id FROM documents "
            "GROUP BY source, source_id HAVING COUNT(*) > 1)"
        ).fetchone()[0])
        fts_enabled = "documents_fts" in tables
        try:
            fts_count = int(conn.execute("SELECT COUNT(*) FROM documents_fts").fetchone()[0]) if fts_enabled else None
            fts_error = None
        except sqlite3.Error as exc:
            fts_count, fts_error = None, str(exc)

        return {
            "database": str(path.resolve()),
            "database_bytes": path.stat().st_size,
            "total_records": total,
            "sources": by_source,
            "quality_checks": {
                "empty_content_records": empty_content,
                "empty_title_records": empty_title,
                "empty_url_records": empty_url,
                "unknown_or_missing_license_records": license_missing,
                "duplicate_source_source_id_groups": duplicate_keys,
            },
            "search_index": {
                "fts5_table_present": fts_enabled,
                "fts5_records": fts_count,
                "fts5_error": fts_error,
            },
            "read_only": True,
        }
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect ARIA's local knowledge corpus without modifying it")
    parser.add_argument("--db", default=DEFAULT_DB, help="Path to ARIA SQLite knowledge database")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    parser.add_argument("--check", action="store_true", help="Exit non-zero if basic corpus quality checks fail")
    args = parser.parse_args(argv)
    try:
        report = inspect_corpus(args.db)
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"ARIA corpus report failed: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Database: {report['database']}")
        print(f"Size: {report['database_bytes']:,} bytes")
        print(f"Total records: {report['total_records']:,}")
        print("\nRecords by source:")
        if report["sources"]:
            for item in report["sources"]:
                print(f"  {item['source']}: {item['records']:,} (latest import: {item['latest_import'] or 'unknown'})")
        else:
            print("  No records imported yet")
        print("\nQuality checks:")
        for key, value in report["quality_checks"].items():
            print(f"  {key}: {value:,}")
        index = report["search_index"]
        print(f"\nFTS5 index present: {index['fts5_table_present']}; indexed records: {index['fts5_records']}")
        if index["fts5_error"]:
            print(f"FTS5 warning: {index['fts5_error']}")
        print("Read-only: yes")

    if args.check:
        quality = report["quality_checks"]
        bad = any(quality[key] > 0 for key in ("empty_content_records", "empty_title_records", "empty_url_records", "duplicate_source_source_id_groups"))
        if report["total_records"] == 0 or bad:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
