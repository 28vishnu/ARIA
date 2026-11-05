"""Explicit, bounded, resumable topic ingestion for ARIA's local knowledge base.

Preview (no network or DB writes): python -m brain.knowledge.knowledge_batch_ingest --db data/aria_open_knowledge.sqlite3
Execute deliberately: add --execute. The target database must already exist.
"""
from __future__ import annotations
import argparse, json, sqlite3, sys
from pathlib import Path
from typing import Any
from brain.knowledge.knowledge_coverage import DEFAULT_TOPICS_FILE, build_coverage_report
from brain.knowledge.open_knowledge import seed_topics


def run_batch(db_path: str | Path, topics_file: str | Path = DEFAULT_TOPICS_FILE,
              batch_size: int = 25, batch_number: int = 1, execute: bool = False,
              delay: float = 0.5, timeout: int = 8) -> dict[str, Any]:
    if not 1 <= batch_size <= 100: raise ValueError("batch_size must be between 1 and 100")
    if batch_number < 1: raise ValueError("batch_number must be 1 or greater")
    if not 0 <= delay <= 5: raise ValueError("delay must be between 0 and 5 seconds")
    if not 1 <= timeout <= 30: raise ValueError("timeout must be between 1 and 30 seconds")
    db = Path(db_path).expanduser()
    if not db.is_file():
        raise FileNotFoundError(f"Knowledge database does not exist: {db}. This command will not create it.")
    plan = build_coverage_report(topics_file=topics_file, db_path=db,
                                 batch_size=batch_size, batch_number=batch_number)
    result: dict[str, Any] = {
        "status": "planned", "execute_requested": bool(execute), "read_only_plan": True,
        "database": str(db.resolve()), "batch_size": batch_size, "batch_number": batch_number,
        "planned_topic_count": len(plan["batch_topics"]),
        "coverage_before": {k: plan[k] for k in ("catalog_topics", "stored_wikipedia_titles",
            "covered_topics", "missing_topics", "coverage_percent", "total_missing_batches")},
        "topics": plan["batch_topics"], "ingestion": None,
    }
    if not execute or not plan["batch_topics"]:
        if execute and not plan["batch_topics"]: result["status"] = "nothing_to_ingest"
        return result
    ingestion = seed_topics(db_path=str(db), topics=plan["batch_topics"],
                            delay=delay, timeout=timeout, limit=batch_size)
    result["status"] = "executed"; result["read_only_plan"] = False
    result["ingestion"] = ingestion
    after = build_coverage_report(topics_file=topics_file, db_path=db,
                                  batch_size=batch_size, batch_number=1)
    result["coverage_after"] = {k: after[k] for k in
        ("covered_topics", "missing_topics", "coverage_percent", "total_missing_batches")}
    return result


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Plan or execute one bounded ARIA knowledge-ingestion batch")
    p.add_argument("--db", required=True, help="Existing ARIA knowledge SQLite database")
    p.add_argument("--topics-file", default=str(DEFAULT_TOPICS_FILE))
    p.add_argument("--batch-size", type=int, default=25)
    p.add_argument("--batch", type=int, default=1)
    p.add_argument("--execute", action="store_true", help="Fetch/store topics; default is preview only")
    p.add_argument("--delay", type=float, default=0.5)
    p.add_argument("--timeout", type=int, default=8)
    a = p.parse_args(argv)
    try:
        report = run_batch(a.db, a.topics_file, a.batch_size, a.batch, a.execute, a.delay, a.timeout)
        print(json.dumps(report, ensure_ascii=False, indent=2)); return 0
    except (OSError, ValueError, sqlite3.Error, RuntimeError) as exc:
        print(f"ARIA knowledge batch failed: {exc}", file=sys.stderr); return 2

if __name__ == "__main__": raise SystemExit(main())
