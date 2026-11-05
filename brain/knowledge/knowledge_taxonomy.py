"""Versioned, data-driven domain catalogue and conservative coverage report.

Taxonomy membership describes a learning/retrieval target; it never implies that
source documents are present. Coverage uses exact normalized document-title matches
only and therefore reports a lower bound rather than semantic coverage.
"""
from __future__ import annotations

import argparse
import json
from functools import lru_cache
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

TAXONOMY_PATH = Path(__file__).with_name("knowledge_taxonomy.json")
REQUIRED_TOPIC_FIELDS = {
    "id", "name", "domain_path", "concepts", "entities", "subtopics", "definition", "explanation_focus", "formula_metadata",
    "relationships", "common_questions", "advanced_questions", "learning_objectives",
    "prerequisites", "related_concepts", "recommended_source_ids",
    "source_quality_requirements",
}


def _walk_topics(taxonomy: dict[str, Any]):
    for domain in taxonomy["domains"]:
        for subject in domain["subjects"]:
            for subdomain in subject["subdomains"]:
                for topic in subdomain["topics"]:
                    yield domain, subject, subdomain, topic


def load_taxonomy(path: str | Path = TAXONOMY_PATH) -> dict[str, Any]:
    """Load and validate stable IDs and the required hierarchical metadata."""
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("Unsupported knowledge taxonomy schema_version")
    domains = data.get("domains")
    if not isinstance(domains, list) or len(domains) != 20:
        raise ValueError("Taxonomy version 1 must define exactly 20 top-level domains")
    ids: set[str] = set()
    relationship_targets: list[tuple[str, str]] = []
    for domain in domains:
        if not isinstance(domain, dict) or not domain.get("id") or not domain.get("name"):
            raise ValueError("Every taxonomy domain requires an id and name")
        if domain["id"] in ids:
            raise ValueError(f"Duplicate taxonomy ID: {domain['id']}")
        ids.add(domain["id"])
        if not isinstance(domain.get("subjects"), list) or not domain["subjects"]:
            raise ValueError(f"Domain {domain['id']} has no subjects")
        for subject in domain["subjects"]:
            if not subject.get("id") or not isinstance(subject.get("subdomains"), list):
                raise ValueError(f"Invalid subject in domain {domain['id']}")
            if subject["id"] in ids:
                raise ValueError(f"Duplicate taxonomy ID: {subject['id']}")
            ids.add(subject["id"])
            for subdomain in subject["subdomains"]:
                if not subdomain.get("id") or not isinstance(subdomain.get("topics"), list):
                    raise ValueError(f"Invalid subdomain in subject {subject['id']}")
                if subdomain["id"] in ids:
                    raise ValueError(f"Duplicate taxonomy ID: {subdomain['id']}")
                ids.add(subdomain["id"])
                for topic in subdomain["topics"]:
                    missing = REQUIRED_TOPIC_FIELDS - topic.keys()
                    if missing:
                        raise ValueError(f"Topic {topic.get('id', '<unknown>')} missing fields: {sorted(missing)}")
                    if topic["id"] in ids:
                        raise ValueError(f"Duplicate taxonomy ID: {topic['id']}")
                    ids.add(topic["id"])
                    if topic["domain_path"] != [domain["id"], subject["id"], subdomain["id"]]:
                        raise ValueError(f"Topic {topic['id']} has an invalid domain_path")
                    if not topic["recommended_source_ids"] or not topic["source_quality_requirements"]:
                        raise ValueError(f"Topic {topic['id']} must define sources and quality requirements")
                    for relationship in topic["relationships"]:
                        if not isinstance(relationship, dict) or not relationship.get("target_id"):
                            raise ValueError(f"Topic {topic['id']} has an invalid relationship")
                        relationship_targets.append((topic["id"], relationship["target_id"]))
    missing_targets = [(source, target) for source, target in relationship_targets if target not in ids]
    if missing_targets:
        raise ValueError(f"Taxonomy relationship targets do not exist: {missing_targets[:5]}")
    data["topic_count"] = sum(1 for _ in _walk_topics(data))
    return data


def list_catalog(kind: str = "domains", domain_id: str | None = None,
                 subject_id: str | None = None, path: str | Path = TAXONOMY_PATH) -> list[dict[str, Any]]:
    taxonomy = load_taxonomy(path)
    if kind not in {"domains", "subjects", "topics"}:
        raise ValueError("kind must be domains, subjects, or topics")
    result: list[dict[str, Any]] = []
    for domain in taxonomy["domains"]:
        if domain_id and domain["id"] != domain_id:
            continue
        if kind == "domains":
            result.append({"id": domain["id"], "name": domain["name"],
                           "subject_count": len(domain["subjects"]),
                           "topic_count": sum(len(sd["topics"]) for s in domain["subjects"] for sd in s["subdomains"])})
            continue
        for subject in domain["subjects"]:
            if subject_id and subject["id"] != subject_id:
                continue
            if kind == "subjects":
                result.append({"id": subject["id"], "name": subject["name"],
                               "domain_id": domain["id"],
                               "subdomain_count": len(subject["subdomains"]),
                               "topic_count": sum(len(sd["topics"]) for sd in subject["subdomains"])})
            else:
                for subdomain in subject["subdomains"]:
                    result.extend({"id": t["id"], "name": t["name"],
                                   "domain_id": domain["id"], "subject_id": subject["id"],
                                   "subdomain_id": subdomain["id"]} for t in subdomain["topics"])
    return result


def _normalize(value: str) -> str:
    return re.sub(r"[^\w ]", "", re.sub(r"[_-]+", " ", str(value or "").casefold())).strip()


def audit_source_references(taxonomy: dict[str, Any] | None = None,
                           registry: dict[str, Any] | None = None) -> dict[str, Any]:
    """Check topic source references against the central rights registry."""
    taxonomy = taxonomy or load_taxonomy()
    if registry is None:
        from brain.knowledge.source_registry import load_registry
        registry = load_registry()
    entries = {str(key).casefold(): value for key, value in registry.get("sources", {}).items()}
    used_domains: dict[str, set[str]] = {}
    for domain, _, _, topic in _walk_topics(taxonomy):
        for source in topic.get("recommended_source_ids", []):
            used_domains.setdefault(str(source).casefold(), set()).add(domain["id"])
    used = set(used_domains)
    unregistered = used - set(entries)
    unsupported = {
        source: sorted(domains - set(entries[source].get("supported_domains", [])))
        for source, domains in used_domains.items() if source in entries
        and domains - set(entries[source].get("supported_domains", []))
    }
    status = "ok" if not unregistered and not unsupported else "source_domain_mismatch"
    return {"registered": sorted(used & set(entries)), "unregistered": sorted(unregistered),
            "unsupported_domain_references": unsupported, "status": status}


@lru_cache(maxsize=1)
def _topic_assignment_index() -> dict[str, dict[str, Any]]:
    """Build a lazy title-to-ID map once for safe record enrichment during imports."""
    taxonomy = load_taxonomy()
    candidates: dict[str, dict[str, dict[str, Any]]] = {}
    for domain, subject, _, topic in _walk_topics(taxonomy):
        assignment = {
            "domain_id": domain["id"], "subject_id": subject["id"],
            "topic_ids": [topic["id"]],
        }
        candidates.setdefault(_normalize(topic["name"]), {})[topic["id"]] = assignment
    return {title: next(iter(choices.values())) for title, choices in candidates.items() if len(choices) == 1}


def topic_assignment(title: str) -> dict[str, Any] | None:
    """Return taxonomy IDs only for an exact normalized title with one catalogue match."""
    assignments = _topic_assignment_index()
    found = assignments.get(_normalize(title))
    return dict(found) if found else None


def coverage_report(db_path: str | Path) -> dict[str, Any]:
    """Report exact-title coverage without creating or mutating the selected DB."""
    taxonomy = load_taxonomy()
    path = Path(db_path).expanduser()
    if not path.is_file():
        return {"database": str(path), "exists": False, "total_documents": 0,
                "coverage_method": "exact normalized title match only", "domains": [
                    {"id": d["id"], "name": d["name"], "topics": sum(len(sd["topics"]) for s in d["subjects"] for sd in s["subdomains"]),
                     "matched_titles": 0, "status": "database_missing"} for d in taxonomy["domains"]]}
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "documents" not in tables:
            raise ValueError("Database has no documents table")
        columns = {r[1] for r in conn.execute("PRAGMA table_info(documents)")}
        if "title" not in columns:
            raise ValueError("Documents table has no title column")
        document_count = int(conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0])
        topic_domains: dict[str, set[str]] = {}
        for domain, _, _, topic in _walk_topics(taxonomy):
            topic_domains.setdefault(_normalize(topic["name"]), set()).add(domain["id"])
        matched_by_domain: dict[str, set[str]] = {d["id"]: set() for d in taxonomy["domains"]}
        for row in conn.execute("SELECT title FROM documents"):
            normalized = _normalize(row[0])
            for domain_id in topic_domains.get(normalized, ()):
                matched_by_domain[domain_id].add(normalized)
        rows = []
        for domain in taxonomy["domains"]:
            topics = [t for _, _, _, t in _walk_topics({"domains": [domain]})]
            matched = sum(_normalize(t["name"]) in matched_by_domain[domain["id"]] for t in topics)
            rows.append({"id": domain["id"], "name": domain["name"], "topics": len(topics),
                         "matched_titles": matched, "coverage_percent": round(matched * 100 / len(topics), 2) if topics else 0,
                         "status": "title_matches_found" if matched else "no_exact_title_matches"})
        return {"database": str(path.resolve()), "exists": True, "total_documents": document_count,
                "catalog_topics": taxonomy["topic_count"], "coverage_method": "exact normalized title match only; semantic/content coverage is not inferred",
                "domains": rows}
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect the versioned JARVIS knowledge taxonomy")
    sub = parser.add_subparsers(dest="command", required=True)
    ls = sub.add_parser("list", help="List taxonomy domains, subjects, or topics")
    ls.add_argument("--kind", choices=("domains", "subjects", "topics"), default="domains")
    ls.add_argument("--domain")
    ls.add_argument("--subject")
    sub.add_parser("validate", help="Validate taxonomy IDs and required fields")
    cov = sub.add_parser("coverage", help="Read-only exact-title coverage report")
    from brain.knowledge.open_knowledge import DEFAULT_DB
    cov.add_argument("--db", default=DEFAULT_DB)
    args = parser.parse_args(argv)
    try:
        if args.command == "list":
            result = list_catalog(args.kind, args.domain, args.subject)
        elif args.command == "validate":
            data = load_taxonomy()
            source_audit = audit_source_references(data)
            result = {"status": "valid", "schema_version": data["schema_version"],
                      "taxonomy_version": data["taxonomy_version"], "domains": len(data["domains"]),
                      "topics": data["topic_count"], "source_reference_audit": source_audit}
            if source_audit["status"] != "ok":
                result["status"] = "invalid_source_references"
        else:
            result = coverage_report(args.db)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.command == "validate" and result.get("status") != "valid":
            return 2
        return 0
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"Knowledge taxonomy operation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
