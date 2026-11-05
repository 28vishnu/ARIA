import sqlite3

import pytest

from brain.knowledge.open_knowledge import (
    backup_database,
    connect,
    import_records,
    restore_database,
    search,
    verify_database,
)


def test_additive_migration_preserves_legacy_documents(tmp_path):
    db = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE documents (id INTEGER PRIMARY KEY, source TEXT, source_id TEXT, title TEXT, content TEXT, url TEXT, language TEXT DEFAULT 'en', imported_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(source, source_id))")
        conn.execute("INSERT INTO documents(source, source_id, title, content, url) VALUES ('wikipedia', '42', 'Photosynthesis', 'Plants convert light into chemical energy.', 'https://en.wikipedia.org/wiki/Photosynthesis')")

    conn = connect(str(db))
    try:
        row = conn.execute("SELECT title, content, canonical_url, domain_id, topic_ids FROM documents WHERE source_id='42'").fetchone()
        assert row[0] == "Photosynthesis"
        assert row[1].startswith("Plants convert")
        assert row[2] == ""
        assert conn.execute("SELECT version FROM knowledge_schema_migrations").fetchone()[0] == 2
    finally:
        conn.close()


def test_import_persists_provenance_hash_dates_and_taxonomy_ids(tmp_path):
    db = tmp_path / "knowledge.sqlite3"
    result = import_records(str(db), [{
        "source": "wikipedia", "source_id": "binary-search", "title": "Binary search",
        "content": "Binary search repeatedly halves a sorted search interval.",
        "url": "https://en.wikipedia.org/wiki/Binary_search", "publication_date": "2025-01-01",
        "license": "CC BY-SA", "metadata": {"edition": "reviewed"},
    }])
    assert result["processed"] == 1
    evidence = search(str(db), "binary search", limit=3)
    assert evidence
    assert evidence[0]["canonical_url"] == "https://en.wikipedia.org/wiki/Binary_search"
    assert "topic.computer_science" in evidence[0]["topic_ids"]
    conn = sqlite3.connect(db)
    try:
        row = conn.execute("SELECT canonical_url, publication_date, retrieval_date, content_hash, topic_ids, metadata_json FROM documents").fetchone()
        assert row[0] == "https://en.wikipedia.org/wiki/Binary_search"
        assert row[1] == "2025-01-01"
        assert row[2]
        assert len(row[3]) == 64
        assert "binary-search" in row[4]
        assert '"edition": "reviewed"' in row[5]
    finally:
        conn.close()


def test_reimport_versions_changed_content_and_preserves_previous_revision(tmp_path):
    db = tmp_path / "versions.sqlite3"
    base = {"source": "test", "source_id": "stable-id", "title": "Versioned topic", "url": "https://example.org/topic"}
    import_records(str(db), [{**base, "content": "First reviewed source text."}])
    import_records(str(db), [{**base, "content": "Updated source text with a correction."}])
    conn = sqlite3.connect(db)
    try:
        current = conn.execute("SELECT document_version, content FROM documents WHERE source_id='stable-id'").fetchone()
        prior = conn.execute("SELECT document_version, content FROM document_history WHERE source_id='stable-id'").fetchone()
        assert current == (2, "Updated source text with a correction.")
        assert prior == (1, "First reviewed source text.")
    finally:
        conn.close()


def test_backup_restore_and_integrity_verification(tmp_path):
    db = tmp_path / "knowledge.sqlite3"
    import_records(str(db), [{"source": "test", "source_id": "one", "title": "Topic", "content": "Evidence content long enough for test.", "url": "https://example.org/topic"}])
    backup = tmp_path / "knowledge-backup.sqlite3"
    result = backup_database(str(db), str(backup))
    assert result["status"] == "backup_created"
    assert verify_database(str(backup))["integrity_check"] == "ok"

    restored = tmp_path / "restored.sqlite3"
    assert restore_database(str(backup), str(restored))["status"] == "restored"
    assert verify_database(str(restored))["documents"] == 1
    with pytest.raises(FileExistsError):
        restore_database(str(backup), str(restored))
