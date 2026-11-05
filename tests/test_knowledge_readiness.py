import json
import sqlite3
from pathlib import Path

from brain.knowledge.knowledge_readiness import build_readiness_report, inspect_database


def make_db(path: Path, with_docs: bool = True):
    with sqlite3.connect(path) as conn:
        if with_docs:
            conn.execute("CREATE TABLE documents (id INTEGER PRIMARY KEY, source TEXT, title TEXT, content TEXT)")
            conn.execute("INSERT INTO documents(source, title, content) VALUES ('test', 'Example', 'Example content')")


def test_inspect_database_does_not_create_missing_database(tmp_path):
    db = tmp_path / "missing.sqlite3"
    checks = inspect_database(db)
    assert not db.exists()
    assert checks[0]["status"] == "error"


def test_inspect_database_reports_missing_documents_table(tmp_path):
    db = tmp_path / "empty.sqlite3"
    sqlite3.connect(db).close()
    checks = inspect_database(db)
    assert any(c["name"] == "documents_table" and c["status"] == "error" for c in checks)


def test_inspect_database_reports_schema_and_optional_tables(tmp_path):
    db = tmp_path / "knowledge.sqlite3"
    make_db(db)
    checks = inspect_database(db)
    statuses = {c["name"]: c["status"] for c in checks}
    assert statuses["documents_schema"] == "ok"
    assert statuses["document_count"] == "ok"
    assert statuses["structured_facts_schema"] == "warning"
    assert statuses["freshness_schedule_schema"] == "warning"


def test_readiness_report_loads_catalog_and_local_artifacts(tmp_path):
    root = Path(__file__).resolve().parents[1]
    db = tmp_path / "knowledge.sqlite3"
    make_db(db)
    report = build_readiness_report(
        db,
        root / "brain/knowledge/core_topics.txt",
        root / "brain/knowledge/source_registry.json",
        root / "brain/knowledge/specialized_docs_manifest.json",
    )
    names = {item["name"] for item in report["checks"]}
    assert report["read_only"] is True
    assert report["status"] == "ready_for_review"
    assert "topic_catalog" in names
    assert "source_registry" in names
    assert "module:retrieval_evaluation.py" in names


def test_readiness_report_flags_bad_registry_and_manifest(tmp_path):
    db = tmp_path / "knowledge.sqlite3"
    make_db(db)
    topics = tmp_path / "topics.txt"
    topics.write_text("Example topic\n", encoding="utf-8")
    registry = tmp_path / "registry.json"
    registry.write_text("{}", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"documents": "not-a-list"}), encoding="utf-8")
    report = build_readiness_report(db, topics, registry, manifest)
    statuses = {item["name"]: item["status"] for item in report["checks"]}
    assert statuses["source_registry"] == "error"
    assert statuses["specialized_docs_manifest"] == "error"
    assert report["status"] == "not_ready"
