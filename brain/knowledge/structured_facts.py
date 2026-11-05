"""Provenance-aware structured facts for ARIA's SQLite knowledge store.

This module deliberately does not infer facts from arbitrary prose. Callers must
supply a fact and its source metadata. Facts are deduplicated and can be queried
without an LLM. Schema creation happens only when initialize_schema() is called.
"""
from __future__ import annotations

import re
import sqlite3
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS structured_entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_name TEXT NOT NULL UNIQUE,
    entity_type TEXT NOT NULL DEFAULT 'general',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS structured_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id INTEGER NOT NULL REFERENCES structured_entities(id),
    relation TEXT NOT NULL,
    object_id INTEGER NOT NULL REFERENCES structured_entities(id),
    confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
    status TEXT NOT NULL DEFAULT 'candidate' CHECK(status IN ('candidate','verified','rejected')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(subject_id, relation, object_id)
);
CREATE TABLE IF NOT EXISTS structured_fact_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fact_id INTEGER NOT NULL REFERENCES structured_facts(id) ON DELETE CASCADE,
    source_name TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_record_id TEXT NOT NULL DEFAULT '',
    license TEXT NOT NULL DEFAULT 'unknown',
    evidence TEXT NOT NULL DEFAULT '',
    added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(fact_id, source_name, source_url, source_record_id)
);
CREATE INDEX IF NOT EXISTS idx_structured_facts_subject_relation
ON structured_facts(subject_id, relation);
CREATE INDEX IF NOT EXISTS idx_structured_facts_status
ON structured_facts(status);
CREATE INDEX IF NOT EXISTS idx_structured_sources_fact
ON structured_fact_sources(fact_id);
"""

_RELATION_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def normalize_entity(value: str) -> str:
    """Trim and collapse whitespace while preserving display capitalization."""
    if not isinstance(value, str):
        raise ValueError("Entity name must be text")
    value = " ".join(value.split())
    if not value or len(value) > 300:
        raise ValueError("Entity name must contain 1-300 characters")
    if any(ord(ch) < 32 for ch in value):
        raise ValueError("Entity name contains control characters")
    return value


def validate_fact(subject: str, relation: str, obj: str, source_name: str,
                  source_url: str, license: str, confidence: float,
                  status: str = "candidate") -> tuple[str, str, str]:
    subject = normalize_entity(subject)
    obj = normalize_entity(obj)
    relation = str(relation or "").strip().lower()
    if not _RELATION_RE.fullmatch(relation):
        raise ValueError("Relation must be lowercase snake_case (1-64 chars)")
    if not str(source_name or "").strip():
        raise ValueError("source_name is required for provenance")
    if not re.match(r"^https?://\S+$", str(source_url or "")):
        raise ValueError("source_url must be an absolute HTTP(S) URL")
    if not str(license or "").strip():
        raise ValueError("license must be recorded; use 'unknown' if unresolved")
    try:
        confidence = float(confidence)
    except (TypeError, ValueError) as exc:
        raise ValueError("confidence must be numeric") from exc
    if not 0 <= confidence <= 1:
        raise ValueError("confidence must be between 0 and 1")
    if status not in {"candidate", "verified", "rejected"}:
        raise ValueError("status must be candidate, verified, or rejected")
    return subject, relation, obj


def initialize_schema(conn: sqlite3.Connection) -> None:
    """Explicitly create structured-fact tables in an existing SQLite connection."""
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    conn.commit()


def _entity_id(conn: sqlite3.Connection, name: str, entity_type: str) -> int:
    conn.execute(
        "INSERT INTO structured_entities(canonical_name, entity_type) VALUES (?, ?) "
        "ON CONFLICT(canonical_name) DO UPDATE SET updated_at=CURRENT_TIMESTAMP",
        (name, entity_type or "general"),
    )
    row = conn.execute(
        "SELECT id FROM structured_entities WHERE canonical_name = ?", (name,)
    ).fetchone()
    return int(row[0])


def add_fact(conn: sqlite3.Connection, *, subject: str, relation: str, obj: str,
             source_name: str, source_url: str, license: str = "unknown",
             source_record_id: str = "", evidence: str = "",
             confidence: float = 0.5, status: str = "candidate",
             subject_type: str = "general", object_type: str = "general") -> int:
    """Insert/update a fact and attach source evidence; returns its fact id.

    Verified status is an explicit caller decision; this function does not
    independently verify factual correctness.
    """
    subject, relation, obj = validate_fact(
        subject, relation, obj, source_name, source_url, license, confidence, status
    )
    conn.execute("PRAGMA foreign_keys = ON")
    sid = _entity_id(conn, subject, subject_type)
    oid = _entity_id(conn, obj, object_type)
    conn.execute(
        "INSERT INTO structured_facts(subject_id, relation, object_id, confidence, status) "
        "VALUES (?, ?, ?, ?, ?) ON CONFLICT(subject_id, relation, object_id) DO UPDATE SET "
        "confidence=MAX(structured_facts.confidence, excluded.confidence), "
        "status=CASE WHEN structured_facts.status='verified' THEN 'verified' "
        "ELSE excluded.status END, updated_at=CURRENT_TIMESTAMP",
        (sid, relation, oid, float(confidence), status),
    )
    row = conn.execute(
        "SELECT id FROM structured_facts WHERE subject_id=? AND relation=? AND object_id=?",
        (sid, relation, oid),
    ).fetchone()
    fact_id = int(row[0])
    conn.execute(
        "INSERT INTO structured_fact_sources(fact_id, source_name, source_url, source_record_id, license, evidence) "
        "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(fact_id, source_name, source_url, source_record_id) "
        "DO UPDATE SET license=excluded.license, evidence=excluded.evidence",
        (fact_id, source_name.strip(), source_url, str(source_record_id or ""),
         license.strip(), str(evidence or "")[:10000]),
    )
    conn.commit()
    return fact_id


def query_facts(conn: sqlite3.Connection, *, entity: str | None = None,
                relation: str | None = None, status: str | None = "verified",
                limit: int = 100) -> list[dict[str, Any]]:
    """Return facts with source provenance; defaults to verified facts only."""
    if not 1 <= int(limit) <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    clauses: list[str] = []
    params: list[Any] = []
    if entity:
        clauses.append("(s.canonical_name = ? OR o.canonical_name = ?)")
        clauses.extend([])
        params.extend([normalize_entity(entity), normalize_entity(entity)])
    if relation:
        rel = str(relation).strip().lower()
        if not _RELATION_RE.fullmatch(rel):
            raise ValueError("Invalid relation")
        clauses.append("f.relation = ?")
        params.append(rel)
    if status is not None:
        if status not in {"candidate", "verified", "rejected"}:
            raise ValueError("Invalid status")
        clauses.append("f.status = ?")
        params.append(status)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = (
        "SELECT f.id, s.canonical_name AS subject, f.relation, o.canonical_name AS object, "
        "f.confidence, f.status, src.source_name, src.source_url, src.source_record_id, "
        "src.license, src.evidence FROM structured_facts f "
        "JOIN structured_entities s ON s.id=f.subject_id "
        "JOIN structured_entities o ON o.id=f.object_id "
        "LEFT JOIN structured_fact_sources src ON src.fact_id=f.id" + where +
        " ORDER BY f.confidence DESC, f.id ASC LIMIT ?"
    )
    params.append(int(limit))
    return [dict(row) for row in conn.execute(sql, params).fetchall()]
