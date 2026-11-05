import json
import sqlite3
from pathlib import Path

from brain.knowledge.jarvis_acceptance import build_report, inspect_database


def make_db(path: Path, rows=()):
    with sqlite3.connect(path) as conn:
        conn.execute('''CREATE TABLE documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL, source_id TEXT NOT NULL, title TEXT NOT NULL,
            content TEXT NOT NULL, url TEXT NOT NULL, license TEXT NOT NULL DEFAULT 'unknown',
            imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(source, source_id)
        )''')
        for row in rows:
            conn.execute(
                'INSERT INTO documents(source, source_id, title, content, url, license) VALUES (?, ?, ?, ?, ?, ?)',
                row,
            )


def test_missing_database_is_reported_without_creating_file(tmp_path):
    path = tmp_path / 'missing.sqlite3'
    checks = inspect_database(path)
    assert not path.exists()
    assert checks[0]['status'] == 'fail'


def test_existing_empty_corpus_fails_nonempty_check(tmp_path):
    path = tmp_path / 'empty.sqlite3'
    make_db(path)
    checks = inspect_database(path)
    assert {c['name']: c['status'] for c in checks}['corpus_nonempty'] == 'fail'


def test_populated_corpus_reports_source_diversity(tmp_path):
    path = tmp_path / 'corpus.sqlite3'
    make_db(path, [
        ('wiki', '1', 'Title one', 'Content one', 'https://example.org/1', 'CC BY-SA'),
        ('docs', '2', 'Title two', 'Content two', 'https://example.org/2', 'MIT'),
    ])
    checks = inspect_database(path)
    status = {c['name']: c['status'] for c in checks}
    assert status['documents_schema'] == 'pass'
    assert status['corpus_nonempty'] == 'pass'
    assert status['source_diversity'] == 'pass'


def test_report_discloses_read_only_limitations(tmp_path):
    path = tmp_path / 'corpus.sqlite3'
    make_db(path, [('wiki', '1', 'Title', 'Content', 'https://example.org', 'CC BY-SA')])
    report = build_report(path)
    assert report['read_only'] is True
    assert any('factual accuracy benchmark' in x for x in report['limitations'])
