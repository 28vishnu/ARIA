"""Read-only acceptance audit for ARIA's knowledge-to-answer pipeline.

This command does not download data, create a database, contact providers, or
change ARIA state. It reports whether key components exist and whether the
configured local corpus can be inspected.

Usage:
  python -m brain.knowledge.jarvis_acceptance
  python -m brain.knowledge.jarvis_acceptance --db /var/data/aria_open_knowledge.sqlite3 --json
  python -m brain.knowledge.jarvis_acceptance --db data/aria_open_knowledge.sqlite3 --strict

Exit codes: 0 = all required checks passed; 1 = required checks failed.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from brain.knowledge.open_knowledge import DEFAULT_DB

ROOT = Path(__file__).resolve().parents[2]

PIPELINE_FILES = {
    "bootstrap": "core/bootstrap.py",
    "knowledge_manager": "brain/knowledge/knowledge_manager.py",
    "local_corpus_importer": "brain/knowledge/open_knowledge.py",
    "retrieval_coordinator": "brain/knowledge/retrieval_coordinator.py",
    "answer_composer": "brain/knowledge/answer_composer.py",
    "source_registry": "brain/knowledge/source_registry.py",
    "retrieval_evaluation": "brain/knowledge/retrieval_evaluation.py",
    "freshness_refresh": "brain/knowledge/daily_knowledge_refresh.py",
    "memory_system": "brain/memory/jarvis_memory_system.py",
    "llm_router": "brain/llm/llm_router.py",
}


def _check(name: str, ok: bool, detail: str, required: bool = True) -> dict[str, Any]:
    return {
        "name": name,
        "status": "pass" if ok else ("fail" if required else "warning"),
        "required": required,
        "detail": detail,
    }


def inspect_database(db_path: str | os.PathLike[str]) -> list[dict[str, Any]]:
    """Inspect an existing corpus read-only. Never initialize or mutate it."""
    path = Path(db_path).expanduser()
    if not path.is_file():
        return [_check("corpus_file", False, f"Database file not found: {path}")]

    try:
        uri = path.resolve().as_uri() + "?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=5) as conn:
            tables = {str(row[0]) for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
            )}
            if "documents" not in tables:
                return [
                    _check("corpus_file", True, f"Found {path.resolve()}"),
                    _check("documents_table", False, "Missing required 'documents' table"),
                ]

            columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(documents)")}
            required_columns = {"id", "source", "source_id", "title", "content", "url"}
            missing = sorted(required_columns - columns)
            if missing:
                return [
                    _check("corpus_file", True, f"Found {path.resolve()}"),
                    _check("documents_schema", False, f"Missing columns: {missing}"),
                ]

            total = int(conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0])
            sources = [
                {"source": str(row[0] or "unknown"), "records": int(row[1])}
                for row in conn.execute(
                    "SELECT source, COUNT(*) FROM documents GROUP BY source ORDER BY COUNT(*) DESC, source"
                )
            ]
            empty = int(conn.execute(
                "SELECT COUNT(*) FROM documents WHERE TRIM(COALESCE(title,''))='' "
                "OR TRIM(COALESCE(content,''))='' OR TRIM(COALESCE(url,''))=''"
            ).fetchone()[0])
            unknown_license = None
            if "license" in columns:
                unknown_license = int(conn.execute(
                    "SELECT COUNT(*) FROM documents WHERE license IS NULL OR TRIM(license)='' "
                    "OR LOWER(TRIM(license))='unknown'"
                ).fetchone()[0])
            fts_present = "documents_fts" in tables
            fts_count = None
            fts_error = None
            if fts_present:
                try:
                    fts_count = int(conn.execute("SELECT COUNT(*) FROM documents_fts").fetchone()[0])
                except sqlite3.Error as exc:
                    fts_error = str(exc)

            return [
                _check("corpus_file", True, f"Found {path.resolve()} ({path.stat().st_size:,} bytes)"),
                _check("documents_schema", True, "Required document columns are present"),
                _check("corpus_nonempty", total > 0, f"{total:,} document(s) stored"),
                _check("record_quality", empty == 0, f"{empty:,} records have an empty title, content or URL", required=False),
                _check("license_metadata", unknown_license == 0 if unknown_license is not None else False,
                       (f"{unknown_license:,} records have missing/unknown licenses" if unknown_license is not None
                        else "No license column; record-level license coverage cannot be measured"), required=False),
                _check("fts_index", fts_present and fts_error is None and (fts_count == total),
                       f"FTS present={fts_present}, indexed={fts_count}, documents={total}, error={fts_error}", required=False),
                _check("source_diversity", len(sources) >= 2,
                       f"{len(sources)} source type(s): {sources}", required=False),
            ]
    except (OSError, sqlite3.Error, ValueError) as exc:
        return [_check("corpus_readable", False, f"Read-only database inspection failed: {exc}")]


def build_report(db_path: str | os.PathLike[str] = DEFAULT_DB) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    for name, relative in PIPELINE_FILES.items():
        path = ROOT / relative
        checks.append(_check(f"module:{name}", path.is_file(), str(path.relative_to(ROOT))))

    registry = ROOT / "brain/knowledge/source_registry.json"
    if registry.is_file():
        try:
            data = json.loads(registry.read_text(encoding="utf-8"))
            sources = data.get("sources") if isinstance(data, dict) else None
            valid = isinstance(sources, (dict, list)) and bool(sources)
            count = len(sources) if isinstance(sources, (dict, list)) else 0
            checks.append(_check("source_registry_data", valid, f"{count} registered source entries"))
        except (OSError, json.JSONDecodeError) as exc:
            checks.append(_check("source_registry_data", False, f"Could not parse registry: {exc}"))
    else:
        checks.append(_check("source_registry_data", False, f"Missing {registry}"))

    manifest = ROOT / "brain/knowledge/specialized_docs_manifest.json"
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        docs = data.get("documents") if isinstance(data, dict) else None
        valid = isinstance(docs, list)
        count = len(docs) if valid else 0
        checks.append(_check("specialized_docs_manifest", valid, f"{count} document entries", required=False))
    except (OSError, json.JSONDecodeError) as exc:
        checks.append(_check("specialized_docs_manifest", False, f"Manifest unavailable/invalid: {exc}", required=False))

    checks.extend(inspect_database(db_path))
    required_failures = sum(c["status"] == "fail" and c["required"] for c in checks)
    return {
        "status": "pass" if required_failures == 0 else "fail",
        "read_only": True,
        "database": str(Path(db_path).expanduser()),
        "summary": {
            "checks": len(checks),
            "passed": sum(c["status"] == "pass" for c in checks),
            "warnings": sum(c["status"] == "warning" for c in checks),
            "required_failures": required_failures,
        },
        "checks": checks,
        "limitations": [
            "This is a structural acceptance audit, not a factual accuracy benchmark.",
            "A passing report does not prove that all knowledge topics are covered.",
            "A passing report does not verify external credentials, live providers, Android runtime, or production state.",
            "The command never creates a database, downloads sources, or changes corpus data.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=os.environ.get("ARIA_OPEN_KNOWLEDGE_DB", str(DEFAULT_DB)))
    parser.add_argument("--json", action="store_true", help="Print JSON report")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero for warnings as well as required failures")
    args = parser.parse_args(argv)
    report = build_report(args.db)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"ARIA knowledge-to-answer acceptance: {report['status'].upper()}")
        print(f"Database: {report['database']}")
        print(f"Checks: {report['summary']['passed']} passed, {report['summary']['warnings']} warnings, "
              f"{report['summary']['required_failures']} required failures")
        for item in report["checks"]:
            print(f"[{item['status'].upper():7}] {item['name']}: {item['detail']}")
        print("\nLimitations:")
        for limitation in report["limitations"]:
            print(f"- {limitation}")
    if report["summary"]["required_failures"]:
        return 1
    if args.strict and report["summary"]["warnings"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
