"""Read-only readiness report for ARIA's knowledge subsystem.

This is a diagnostic, not a deployment or data-ingestion command. It checks local
artifacts and an existing SQLite database without creating tables or changing rows.

Example:
  python -m brain.knowledge.knowledge_readiness --db data/aria_open_knowledge.sqlite3
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sqlite3
from pathlib import Path
from typing import Any

from brain.knowledge.open_knowledge import DEFAULT_DB, read_topics_file

ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_DIR = Path(__file__).resolve().parent
DEFAULT_TOPICS = KNOWLEDGE_DIR / "core_topics.txt"
DEFAULT_REGISTRY = KNOWLEDGE_DIR / "source_registry.json"
DEFAULT_MANIFEST = KNOWLEDGE_DIR / "specialized_docs_manifest.json"
REQUIRED_DOCUMENT_COLUMNS = {"source", "title", "content"}
OPTIONAL_INTEGRATION_MODULES = (
    "knowledge_coverage.py",
    "source_registry.py",
    "knowledge_batch_ingest.py",
    "structured_facts.py",
    "specialized_docs.py",
    "knowledge_freshness.py",
    "retrieval_evaluation.py",
)


def _check(name: str, ok: bool, detail: str, severity: str = "error") -> dict[str, Any]:
    return {"name": name, "status": "ok" if ok else severity, "detail": detail}


def inspect_database(db_path: str | Path) -> list[dict[str, Any]]:
    path = Path(db_path).expanduser()
    if not path.is_file():
        return [_check("database_exists", False, f"Database does not exist: {path}")]
    try:
        uri = path.resolve().as_uri() + "?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=5) as conn:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            checks = [_check("database_exists", True, str(path.resolve()))]
            if "documents" not in tables:
                checks.append(_check("documents_table", False, "Missing required table 'documents'"))
                return checks
            columns = {r[1] for r in conn.execute("PRAGMA table_info(documents)")}
            missing = sorted(REQUIRED_DOCUMENT_COLUMNS - columns)
            checks.append(_check("documents_schema", not missing,
                                 "Required columns present" if not missing else f"Missing columns: {missing}"))
            count = int(conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0])
            checks.append(_check("document_count", count > 0,
                                 f"{count} document(s) stored", severity="warning"))
            structured = {"structured_entities", "structured_facts", "structured_fact_sources"}
            present = structured & tables
            checks.append(_check("structured_facts_schema", present == structured,
                                 "All structured-fact tables present" if present == structured
                                 else f"Structured-fact tables present: {sorted(present)}; missing: {sorted(structured - present)}",
                                 severity="warning"))
            freshness = "knowledge_review_schedule" in tables
            checks.append(_check("freshness_schedule_schema", freshness,
                                 "Review schedule table present" if freshness else "Review schedule table not initialized",
                                 severity="warning"))
            return checks
    except (sqlite3.Error, OSError, ValueError) as exc:
        return [_check("database_readable", False, f"Read-only inspection failed: {exc}")]


def build_readiness_report(
    db_path: str | Path = DEFAULT_DB,
    topics_path: str | Path = DEFAULT_TOPICS,
    registry_path: str | Path = DEFAULT_REGISTRY,
    manifest_path: str | Path = DEFAULT_MANIFEST,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    topics_file = Path(topics_path).expanduser()
    try:
        topics = read_topics_file(str(topics_file)) if topics_file.is_file() else []
        checks.append(_check("topic_catalog", bool(topics),
                             f"{len(topics)} topic entries loaded from {topics_file}" if topics
                             else f"Missing or empty topic catalog: {topics_file}"))
    except Exception as exc:
        checks.append(_check("topic_catalog", False, f"Could not read topic catalog: {exc}"))

    try:
        from brain.knowledge.source_registry import load_registry
        registry = load_registry(registry_path)
        checks.append(_check("source_registry", True,
                             f"Schema v{registry['schema_version']}; {len(registry['sources'])} registered source(s)"))
    except Exception as exc:
        checks.append(_check("source_registry", False, f"Registry invalid/unavailable: {exc}"))

    try:
        data = json.loads(Path(manifest_path).expanduser().read_text(encoding="utf-8"))
        docs = data.get("documents") if isinstance(data, dict) else None
        valid = isinstance(docs, list)
        checks.append(_check("specialized_docs_manifest", valid,
                             f"Manifest valid with {len(docs)} document entries" if valid
                             else "Manifest must be a JSON object with a documents list"))
    except Exception as exc:
        checks.append(_check("specialized_docs_manifest", False, f"Manifest invalid/unavailable: {exc}"))

    for filename in OPTIONAL_INTEGRATION_MODULES:
        path = KNOWLEDGE_DIR / filename
        checks.append(_check(f"module:{filename}", path.is_file(),
                             str(path) if path.is_file() else f"Missing module: {path}"))

    checks.extend(inspect_database(db_path))
    error_count = sum(c["status"] == "error" for c in checks)
    warning_count = sum(c["status"] == "warning" for c in checks)
    return {
        "status": "ready_for_review" if error_count == 0 else "not_ready",
        "read_only": True,
        "database": str(Path(db_path).expanduser()),
        "summary": {"checks": len(checks), "errors": error_count, "warnings": warning_count,
                    "passed": sum(c["status"] == "ok" for c in checks)},
        "checks": checks,
        "limitations": [
            "This report checks local files and schema presence; it does not validate factual correctness.",
            "A missing optional schema is reported as a warning and is not initialized automatically.",
            "A successful report does not mean the service is deployed or that every topic is ingested.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DEFAULT_DB), help="Existing SQLite knowledge database")
    parser.add_argument("--topics", default=str(DEFAULT_TOPICS))
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--json-out", help="Optional report path; parent directory must already exist")
    args = parser.parse_args(argv)
    report = build_readiness_report(args.db, args.topics, args.registry, args.manifest)
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    print(rendered)
    if args.json_out:
        out = Path(args.json_out).expanduser()
        if not out.parent.is_dir():
            parser.error(f"Report output directory does not exist: {out.parent}")
        out.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report["status"] == "ready_for_review" else 1


if __name__ == "__main__":
    raise SystemExit(main())
