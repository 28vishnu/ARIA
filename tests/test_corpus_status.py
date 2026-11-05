import sqlite3

import pytest

from brain.knowledge.corpus_status import inspect_corpus, main


def make_db(path, rows=()):
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT NOT NULL,
        source_id TEXT NOT NULL,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        url TEXT NOT NULL,
        language TEXT NOT NULL DEFAULT 'en',
        license TEXT NOT NULL DEFAULT 'unknown',
        imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(source, source_id)
    )""")
    for row in rows:
        conn.execute("INSERT INTO documents(source, source_id, title, content, url, license) VALUES (?, ?, ?, ?, ?, ?)", row)
    conn.commit()
    conn.close()


def test_reports_empty_corpus_read_only(tmp_path):
    db = tmp_path / "knowledge.sqlite3"
    make_db(db)
    before = db.read_bytes()
    report = inspect_corpus(db)
    assert report["total_records"] == 0
    assert report["sources"] == []
    assert report["read_only"] is True
    assert db.read_bytes() == before


def test_counts_records_and_quality_flags(tmp_path):
    db = tmp_path / "knowledge.sqlite3"
    make_db(db, [
        ("wikipedia", "1", "Photosynthesis", "Plants convert light energy.", "https://example.org/1", "CC BY-SA"),
        ("wikipedia", "2", "Unknown license page", "Content", "https://example.org/2", "unknown"),
        ("gutenberg", "3", "Novel", "Story", "https://example.org/3", "Public domain"),
    ])
    report = inspect_corpus(db)
    assert report["total_records"] == 3
    assert {item["source"]: item["records"] for item in report["sources"]} == {"wikipedia": 2, "gutenberg": 1}
    assert report["quality_checks"]["unknown_or_missing_license_records"] == 1
    assert report["quality_checks"]["empty_content_records"] == 0


def test_missing_database_does_not_create_it(tmp_path):
    db = tmp_path / "missing.sqlite3"
    with pytest.raises(FileNotFoundError):
        inspect_corpus(db)
    assert not db.exists()


def test_missing_documents_table_is_rejected(tmp_path):
    db = tmp_path / "wrong.sqlite3"
    sqlite3.connect(db).close()
    with pytest.raises(ValueError, match="documents"):
        inspect_corpus(db)


def test_cli_json_and_check(tmp_path, capsys):
    db = tmp_path / "knowledge.sqlite3"
    make_db(db, [("wiki", "1", "Title", "Body", "https://example.org", "CC BY-SA")])
    assert main(["--db", str(db), "--json", "--check"]) == 0
    assert '"total_records": 1' in capsys.readouterr().out


def test_cli_check_fails_for_empty_corpus(tmp_path):
    db = tmp_path / "knowledge.sqlite3"
    make_db(db)
    assert main(["--db", str(db), "--check"]) == 1
