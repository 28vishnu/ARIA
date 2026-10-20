import sqlite3

from brain.knowledge.knowledge_domains import DOMAINS, audit_coverage, sync_topics
from brain.knowledge.open_knowledge import connect, import_records


def test_all_requested_domains_are_present():
    assert set(DOMAINS) == {
        "computer_science", "science_math", "general_knowledge", "education", "current_knowledge"
    }
    assert all(domain["topics"] for domain in DOMAINS.values())


def test_audit_reports_records_in_shared_corpus(tmp_path):
    db = tmp_path / "knowledge.sqlite3"
    import_records(str(db), [
        {"source": "test", "source_id": "py", "title": "Python programming language", "content": "Python is a programming language used for software development.", "url": "https://docs.python.org/3/"},
        {"source": "test", "source_id": "physics", "title": "Physics", "content": "Physics studies matter, energy, and their interactions.", "url": "https://openstax.org/subjects/science"},
    ])
    report = audit_coverage(str(db))
    assert report["total_records"] == 2
    assert report["domains"]["computer_science"]["matched_records"] >= 1
    assert report["domains"]["science_math"]["matched_records"] >= 1


def test_sync_rejects_unknown_domain_before_network(tmp_path):
    try:
        sync_topics(str(tmp_path / "db.sqlite3"), domain="not_a_domain", limit_per_domain=1, delay=0)
    except ValueError as exc:
        assert "Unknown domain" in str(exc)
    else:
        raise AssertionError("unknown domain should fail")
