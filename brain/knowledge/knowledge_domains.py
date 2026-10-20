"""Unified subject coverage and incremental bootstrap for ARIA's local knowledge.

This module does not manufacture facts. It uses the existing Wikimedia importer for
small seed batches, the existing RSS collector for dated updates, and the existing
local dataset importers for larger licensed collections. All records land in the
same documents table so the current retrieval layer can search them together.

Examples:
  python -m brain.knowledge.knowledge_domains catalog
  python -m brain.knowledge.knowledge_domains audit --db data/aria_open_knowledge.sqlite3
  python -m brain.knowledge.knowledge_domains sync --domain computer_science --limit-per-domain 8
  python -m brain.knowledge.knowledge_domains sync --domain all --limit-per-domain 5 --include-news
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

from brain.knowledge.open_knowledge import DEFAULT_DB, fetch_and_store_topic

DOMAINS: dict[str, dict[str, Any]] = {
    "computer_science": {
        "label": "Computer science and software engineering",
        "topics": [
            "Python (programming language)", "Java (programming language)", "C++", "Algorithms",
            "Data structure", "Operating system", "Database", "Computer network",
            "Cybersecurity", "Computer architecture", "Compiler", "Distributed computing",
            "Software engineering", "Git", "HTTP", "TCP/IP", "Cryptography",
            "Machine learning", "Artificial intelligence", "Computer science",
        ],
        "bulk_sources": ["Stack Exchange data dumps", "official language and platform documentation"],
    },
    "science_math": {
        "label": "Science and mathematics",
        "topics": [
            "Physics", "Chemistry", "Biology", "Mathematics", "Statistics", "Calculus",
            "Linear algebra", "Probability", "Thermodynamics", "Quantum mechanics",
            "Genetics", "Evolution", "Cell biology", "Astronomy", "Scientific method",
            "Ecology", "Periodic table", "Electromagnetism", "Relativity", "Climate science",
        ],
        "bulk_sources": ["OpenStax open textbooks", "PubMed metadata and abstracts where permitted"],
    },
    "general_knowledge": {
        "label": "General knowledge, geography, history, and everyday explanations",
        "topics": [
            "Geography", "World history", "World War II", "Ancient history", "Indian history",
            "Constitution of India", "United Nations", "World map", "Ocean", "Earthquake",
            "Volcano", "Water cycle", "Economics", "Philosophy", "Logic", "Civics",
            "Renewable energy", "Human body", "Nutrition", "Critical thinking",
        ],
        "bulk_sources": ["Wikipedia dumps", "Wikidata dumps"],
    },
    "education": {
        "label": "Education and open educational resources",
        "topics": [
            "Open educational resources", "Learning", "Pedagogy", "Mathematics education",
            "Computer science education", "Physics education", "Chemistry education",
            "Biology education", "Study skills", "Scientific literacy", "Information literacy",
            "Academic writing", "Research methods", "Critical reading", "Open textbook",
        ],
        "bulk_sources": ["OpenStax", "Open textbooks with compatible licenses", "Project Gutenberg public-domain texts"],
    },
    "current_knowledge": {
        "label": "Current knowledge, verified news, and official documentation",
        "topics": [
            "Scientific discovery", "Technology news", "Space exploration", "Software release",
            "Cybersecurity advisory", "Climate change", "Public health", "Artificial intelligence research",
        ],
        "bulk_sources": ["dated RSS feeds already configured in knowledge_hub", "official documentation archives"],
    },
}

# Subject-specific trusted starting points for operators. Bulk imports must respect
# each collection's current license, attribution, robots, and redistribution terms.
SOURCE_CATALOG = [
    {"name": "Wikimedia", "kind": "incremental API and optional bulk dumps", "domains": ["computer_science", "science_math", "general_knowledge", "education"], "url": "https://www.wikipedia.org/", "license_note": "Wikipedia content generally CC BY-SA/GFDL; retain attribution and verify terms."},
    {"name": "Wikidata", "kind": "structured facts and optional bulk dump", "domains": ["general_knowledge", "science_math"], "url": "https://www.wikidata.org/", "license_note": "Structured data is generally CC0; verify dump terms."},
    {"name": "Official developer documentation", "kind": "downloaded HTML/Markdown archive import", "domains": ["computer_science", "current_knowledge"], "url": "https://docs.python.org/3/", "license_note": "Check the license of each project; preserve attribution."},
    {"name": "OpenStax", "kind": "open textbook import", "domains": ["science_math", "education"], "url": "https://openstax.org/subjects", "license_note": "Check each book license; some are non-commercial."},
    {"name": "Stack Exchange", "kind": "official data dump import", "domains": ["computer_science"], "url": "https://archive.org/details/stackexchange", "license_note": "Preserve CC BY-SA attribution and post links."},
    {"name": "PubMed", "kind": "biomedical metadata/abstract import", "domains": ["science_math"], "url": "https://pubmed.ncbi.nlm.nih.gov/download/", "license_note": "Rights vary by record and publisher; metadata does not imply full-text rights."},
    {"name": "Project Gutenberg", "kind": "public-domain text import", "domains": ["education", "general_knowledge"], "url": "https://www.gutenberg.org/", "license_note": "Verify public-domain status in the relevant jurisdiction."},
    {"name": "ARIA dated RSS feeds", "kind": "scheduled feed ingestion", "domains": ["current_knowledge"], "url": "https://www.nasa.gov/news-release/feed/", "license_note": "Store publication dates and source links; summaries are not substitutes for full articles."},
]


def audit_coverage(db_path: str = DEFAULT_DB) -> dict[str, Any]:
    """Read-only approximate coverage report based on title/content keyword matches."""
    path = Path(db_path).expanduser()
    if not path.is_file():
        return {"database": str(path), "exists": False, "total_records": 0, "domains": {key: {"label": value["label"], "matched_records": 0, "status": "missing_database"} for key, value in DOMAINS.items()}}
    conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True, timeout=10)
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "documents" not in tables:
            return {"database": str(path.resolve()), "exists": True, "total_records": 0, "domains": {key: {"label": value["label"], "matched_records": 0, "status": "documents_table_missing"} for key, value in DOMAINS.items()}}
        total = int(conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0])
        # Scan titles first and a bounded content prefix; this is a health estimate, not semantic evaluation.
        rows = conn.execute("SELECT title, substr(content,1,3000), source FROM documents").fetchall()
        reports = {}
        for key, domain in DOMAINS.items():
            needles = {re.sub(r"[^a-z0-9]+", " ", t.lower()).strip() for t in domain["topics"]}
            needles |= {word for phrase in list(needles) for word in phrase.split() if len(word) >= 5}
            matches = 0
            sources: dict[str, int] = {}
            for title, content, source in rows:
                haystack = re.sub(r"[^a-z0-9]+", " ", f"{title or ''} {content or ''}".lower())
                if any(term and term in haystack for term in needles):
                    matches += 1
                    sources[str(source or "unknown")] = sources.get(str(source or "unknown"), 0) + 1
            reports[key] = {
                "label": domain["label"], "matched_records": matches,
                "status": "has_matches" if matches else "needs_ingestion",
                "top_sources": sorted(sources.items(), key=lambda pair: pair[1], reverse=True)[:5],
                "coverage_method": "approximate title/content keyword overlap; not a correctness score",
            }
        return {"database": str(path.resolve()), "exists": True, "total_records": total, "domains": reports}
    finally:
        conn.close()


def sync_topics(db_path: str = DEFAULT_DB, domain: str = "all", limit_per_domain: int = 5, include_news: bool = False, delay: float = 0.25) -> dict[str, Any]:
    """Incrementally fetch topic summaries into the same local corpus."""
    if limit_per_domain < 0:
        raise ValueError("limit_per_domain must be zero or greater")
    if delay < 0:
        raise ValueError("delay must be zero or greater")
    selected = list(DOMAINS) if domain == "all" else [domain]
    unknown = [item for item in selected if item not in DOMAINS]
    if unknown:
        raise ValueError("Unknown domain(s): " + ", ".join(unknown))
    result: dict[str, Any] = {"database": str(Path(db_path).expanduser()), "domains": {}, "include_news": include_news}
    for domain_key in selected:
        outcomes = []
        for topic in DOMAINS[domain_key]["topics"][:limit_per_domain]:
            try:
                item = fetch_and_store_topic(db_path, topic, language="en", timeout=12)
                outcomes.append({"topic": topic, "stored": int(item.get("processed", item.get("stored", 0)) or 0), "reason": item.get("reason")})
            except Exception as exc:  # keep the batch moving; preserve per-topic diagnostics
                outcomes.append({"topic": topic, "stored": 0, "error": type(exc).__name__})
            if delay:
                time.sleep(delay)
        result["domains"][domain_key] = {
            "label": DOMAINS[domain_key]["label"], "requested_topics": len(outcomes),
            "stored_records": sum(item["stored"] for item in outcomes), "topics": outcomes,
        }
    if include_news:
        from brain.knowledge.knowledge_hub import collect_news_and_updates
        try:
            result["news"] = collect_news_and_updates(force=True, db_path=db_path)
        except Exception as exc:
            result["news"] = {"error": type(exc).__name__, "message": str(exc)[:300]}
    result["coverage_after_sync"] = audit_coverage(db_path)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Unified ARIA knowledge domain catalog, audit, and incremental sync")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("catalog", help="Show subject domains and suggested sources")
    audit = sub.add_parser("audit", help="Read-only approximate subject coverage report")
    audit.add_argument("--db", default=DEFAULT_DB)
    sync = sub.add_parser("sync", help="Fetch small Wikimedia topic batches into the unified corpus")
    sync.add_argument("--db", default=DEFAULT_DB)
    sync.add_argument("--domain", choices=["all", *DOMAINS], default="all")
    sync.add_argument("--limit-per-domain", type=int, default=5)
    sync.add_argument("--include-news", action="store_true", help="Also force one dated RSS news collection run")
    sync.add_argument("--delay", type=float, default=0.25, help="Seconds between topic requests")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "catalog":
            print(json.dumps({"domains": DOMAINS, "sources": SOURCE_CATALOG}, ensure_ascii=False, indent=2))
        elif args.command == "audit":
            print(json.dumps(audit_coverage(args.db), ensure_ascii=False, indent=2))
        elif args.command == "sync":
            print(json.dumps(sync_topics(args.db, args.domain, args.limit_per_domain, args.include_news, args.delay), ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"ARIA knowledge domain operation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
