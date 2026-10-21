from datetime import datetime, timezone

from brain.knowledge.evidence_policy import (
    apply_evidence_metadata_policy,
    normalize_source_url,
)
from brain.knowledge.knowledge_manager import KnowledgeManager


def test_normalizes_public_http_url_and_removes_fragment():
    assert normalize_source_url("HTTPS://Docs.Python.org/3/tutorial/#lists") == (
        "https://docs.python.org/3/tutorial/"
    )


def test_rejects_non_http_private_and_credential_urls():
    assert normalize_source_url("javascript:alert(1)") == ""
    assert normalize_source_url("http://localhost/admin") == ""
    assert normalize_source_url("http://127.0.0.1/admin") == ""
    assert normalize_source_url("https://user:pass@example.org/path") == ""


def test_invalid_citation_url_does_not_discard_evidence_content():
    record = apply_evidence_metadata_policy({
        "source": "local_corpus",
        "title": "Python lists",
        "content": "Python lists are ordered collections.",
        "url": "javascript:alert(1)",
    })
    assert record["content"] == "Python lists are ordered collections."
    assert record["url"] == ""
    assert record["citation_url_rejected"] is True
    assert record["evidence_id"]


def test_publication_date_sets_conservative_freshness_without_overriding_explicit_score():
    now = datetime(2026, 10, 21, tzinfo=timezone.utc)
    old = apply_evidence_metadata_policy({
        "source": "example",
        "content": "A sourced fact with a publication date.",
        "url": "https://example.org/fact",
        "published_at": "2024-01-01T00:00:00Z",
        "freshness": 0.9,
    }, now=now)
    assert old["freshness_status"] == "stale"
    assert old["freshness"] == 0.9
    assert old["source_age_days"] > 365


def test_publication_date_can_drive_freshness_when_explicitly_enabled():
    now = datetime(2026, 10, 21, tzinfo=timezone.utc)
    recent = apply_evidence_metadata_policy({
        "source": "example",
        "content": "A recent fact.",
        "published_at": "2026-10-01T00:00:00Z",
        "freshness_from_date": True,
    }, now=now)
    assert recent["freshness_status"] == "fresh"
    assert recent["freshness"] == 1.0


def test_invalid_dates_are_not_assumed_fresh():
    record = apply_evidence_metadata_policy({
        "source": "example", "content": "A fact.", "published_at": "last Tuesday"
    })
    assert record["freshness_status"] == "unknown_invalid_date"


def test_knowledge_manager_normalizer_attaches_evidence_identity_and_url_policy():
    manager = KnowledgeManager(None, None, None)
    record = manager._normalize_evidence({
        "source": "docs",
        "title": "Python lists",
        "content": "Python lists are ordered collections.",
        "url": "https://DOCS.PYTHON.ORG/3/tutorial/#lists",
    })
    assert record["url"] == "https://docs.python.org/3/tutorial/"
    assert record["citation_url_valid"] is True
    assert len(record["evidence_id"]) == 24
