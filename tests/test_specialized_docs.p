import json
import sqlite3
from pathlib import Path
import pytest
from brain.knowledge.specialized_docs import import_specialized_docs, load_manifest


def make_pack(tmp_path, *, source_url="https://example.org/guide", rel="guide.md", content=None):
    root = tmp_path / "docs"; root.mkdir(exist_ok=True)
    (root / rel).write_text(content or ("A curated specialist guide with practical explanations and references. " * 3), encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"documents": [{"id": "guide-1", "title": "Specialist Guide", "domain": "software",
        "path": rel, "source_url": source_url, "license": "CC-BY-4.0", "language": "en"}]}), encoding="utf-8")
    return root, manifest


def test_preview_does_not_write_database(tmp_path):
    root, manifest = make_pack(tmp_path)
    db = tmp_path / "knowledge.db"; conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE documents (id INTEGER PRIMARY KEY, source TEXT, source_id TEXT, title TEXT, content TEXT, url TEXT, language TEXT, license TEXT)")
    conn.commit(); conn.close()
    result = import_specialized_docs(db, manifest, root)
    assert result["status"] == "preview" and result["document_count"] == 1
    conn = sqlite3.connect(db); assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0; conn.close()


def test_explicit_import_and_idempotency(tmp_path):
    root, manifest = make_pack(tmp_path)
    db = tmp_path / "knowledge.db"; conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE documents (id INTEGER PRIMARY KEY, source TEXT, source_id TEXT, title TEXT, content TEXT, url TEXT, language TEXT, license TEXT, UNIQUE(source, source_id))")
    conn.commit(); conn.close()
    first = import_specialized_docs(db, manifest, root, execute=True)
    second = import_specialized_docs(db, manifest, root, execute=True)
    assert first["inserted"] == 1 and second["skipped_existing"] == 1


def test_missing_db_is_not_created(tmp_path):
    root, manifest = make_pack(tmp_path); db = tmp_path / "missing.db"
    with pytest.raises(FileNotFoundError): import_specialized_docs(db, manifest, root, execute=True)
    assert not db.exists()


def test_rejects_http_source(tmp_path):
    root, manifest = make_pack(tmp_path, source_url="http://example.org/guide")
    with pytest.raises(ValueError, match="HTTPS"): load_manifest(manifest, root)


def test_rejects_path_traversal(tmp_path):
    root, manifest = make_pack(tmp_path, rel="../outside.md")
    with pytest.raises(ValueError, match="Unsafe document path"): load_manifest(manifest, root)


def test_rejects_duplicate_ids(tmp_path):
    root, manifest = make_pack(tmp_path)
    data = json.loads(manifest.read_text()); data["documents"].append(dict(data["documents"][0]))
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="Duplicate document id"): load_manifest(manifest, root)
