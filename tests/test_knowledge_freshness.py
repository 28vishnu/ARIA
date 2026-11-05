import sqlite3
from datetime import datetime, timezone
from pathlib import Path
import pytest
from brain.knowledge.knowledge_freshness import audit_freshness, schedule_reviews, FRESHNESS_TABLE

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


def make_db(path: Path):
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, source_id TEXT NOT NULL,
        title TEXT NOT NULL, content TEXT NOT NULL, url TEXT NOT NULL,
        language TEXT NOT NULL DEFAULT 'en', license TEXT NOT NULL DEFAULT 'unknown',
        imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(source, source_id))""")
    conn.execute("INSERT INTO documents(source,source_id,title,content,url,imported_at) VALUES (?,?,?,?,?,?)",
                 ("test", "old", "Old doc", "body", "https://example.org/old", "2025-01-01T00:00:00+00:00"))
    conn.execute("INSERT INTO documents(source,source_id,title,content,url,imported_at) VALUES (?,?,?,?,?,?)",
                 ("test", "new", "New doc", "body", "https://example.org/new", "2026-10-01T00:00:00+00:00"))
    conn.commit(); conn.close()


def test_audit_classifies_old_and_new_and_does_not_mutate(tmp_path):
    db = tmp_path / "knowledge.sqlite"
    make_db(db)
    result = audit_freshness(db, max_age_days=180, now=NOW)
    assert result["counts"] == {"fresh": 1, "stale": 1, "unknown": 0, "review_due": 0}
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT name FROM sqlite_master WHERE name=?", (FRESHNESS_TABLE,)).fetchone() is None
    conn.close()


def test_schedule_defaults_to_preview(tmp_path):
    db = tmp_path / "knowledge.sqlite"
    make_db(db)
    result = schedule_reviews(db, execute=False, now=NOW)
    assert result["status"] == "preview"
    assert result["documents_considered"] == 2
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT name FROM sqlite_master WHERE name=?", (FRESHNESS_TABLE,)).fetchone() is None
    conn.close()


def test_execute_persists_review_schedule(tmp_path):
    db = tmp_path / "knowledge.sqlite"
    make_db(db)
    result = schedule_reviews(db, review_interval_days=30, execute=True, now=NOW)
    assert result["status"] == "scheduled" and result["scheduled_count"] == 2
    conn = sqlite3.connect(db)
    assert conn.execute(f"SELECT COUNT(*) FROM {FRESHNESS_TABLE}").fetchone()[0] == 2
    conn.close()
    audit = audit_freshness(db, now=NOW)
    assert audit["counts"]["review_due"] == 0
    assert all(d["review_status"] == "scheduled" for d in audit["documents"])


def test_due_review_detected(tmp_path):
    db = tmp_path / "knowledge.sqlite"
    make_db(db)
    schedule_reviews(db, execute=True, now=NOW)
    later = datetime(2027, 2, 1, tzinfo=timezone.utc)
    result = audit_freshness(db, now=later)
    assert result["counts"]["review_due"] == 2


def test_missing_db_is_not_created(tmp_path):
    db = tmp_path / "missing.sqlite"
    with pytest.raises(FileNotFoundError):
        audit_freshness(db)
    assert not db.exists()


def test_invalid_age_rejected(tmp_path):
    db = tmp_path / "knowledge.sqlite"
    make_db(db)
    with pytest.raises(ValueError):
        audit_freshness(db, max_age_days=0)
