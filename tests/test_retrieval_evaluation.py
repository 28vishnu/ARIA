import json
import sqlite3
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from brain.knowledge.retrieval_evaluation import build_gap_report, evaluate_cases, load_documents, retrieve, tokens


def make_db(path):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE documents (id INTEGER PRIMARY KEY, source TEXT NOT NULL, source_id TEXT NOT NULL, title TEXT NOT NULL, content TEXT NOT NULL, url TEXT NOT NULL)")
    conn.executemany("INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?)", [
        (1, "manual", "a", "Python functions", "Functions define reusable blocks of code.", "https://example.org/python"),
        (2, "manual", "b", "Database indexes", "Indexes can speed up database queries.", "https://example.org/db"),
    ])
    conn.commit(); conn.close()


def test_tokens_case_insensitive():
    assert tokens("Python PYTHON, code!") == {"python", "code"}


def test_retrieve_title_weight_and_rank(tmp_path):
    db = tmp_path / "kb.sqlite"
    make_db(db)
    docs = load_documents(db)
    results = retrieve("Python functions", docs)
    assert results[0]["title"] == "Python functions"
    assert results[0]["score"] > 0


def test_evaluate_cases_pass_and_fail(tmp_path):
    db = tmp_path / "kb.sqlite"
    make_db(db)
    report = evaluate_cases(db, [{"id": "p", "query": "Python functions", "expected_terms": ["Python"]},
                                 {"id": "f", "query": "quantum volcano", "expected_terms": ["quantum"]}], minimum_score=0.15)
    assert report["case_count"] == 2
    assert report["passed_cases"] == 1
    assert report["failed_cases"] == 1
    assert report["read_only"] is True


def test_gap_report_is_transparent(tmp_path):
    db = tmp_path / "kb.sqlite"
    make_db(db)
    report = evaluate_cases(db, [{"query": "unknown subject"}])
    gaps = build_gap_report(report)
    assert gaps["identified_gaps"] == 1
    assert "not proof" in gaps["limitation"]


def test_missing_database_not_created(tmp_path):
    db = tmp_path / "missing.sqlite"
    with pytest.raises(FileNotFoundError):
        load_documents(db)
    assert not db.exists()


def test_invalid_top_k(tmp_path):
    db = tmp_path / "kb.sqlite"
    make_db(db)
    with pytest.raises(ValueError):
        retrieve("Python", load_documents(db), 0)


def test_invalid_cases_and_score(tmp_path):
    db = tmp_path / "kb.sqlite"
    make_db(db)
    with pytest.raises(ValueError):
        evaluate_cases(db, [{"query": "  "}])
    with pytest.raises(ValueError):
        evaluate_cases(db, [], minimum_score=1.1)
