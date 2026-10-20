import sqlite3
import pytest
from brain.knowledge.structured_facts import initialize_schema, add_fact, query_facts, validate_fact

@pytest.fixture
def conn():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    initialize_schema(db)
    yield db
    db.close()

def test_add_and_query_verified_fact_with_provenance(conn):
    fact_id = add_fact(conn, subject="Japan", relation="capital", obj="Tokyo",
        source_name="Test source", source_url="https://example.org/japan",
        license="CC0", confidence=0.99, status="verified", evidence="Explicit source excerpt")
    rows = query_facts(conn, entity="Tokyo")
    assert rows[0]["id"] == fact_id
    assert rows[0]["subject"] == "Japan"
    assert rows[0]["object"] == "Tokyo"
    assert rows[0]["source_url"] == "https://example.org/japan"
    assert rows[0]["status"] == "verified"

def test_candidate_hidden_from_default_verified_query(conn):
    add_fact(conn, subject="A", relation="related_to", obj="B", source_name="S",
        source_url="https://example.org/a", license="unknown", status="candidate")
    assert query_facts(conn) == []
    assert len(query_facts(conn, status="candidate")) == 1

def test_duplicate_fact_keeps_provenance_records(conn):
    args = dict(subject="A", relation="related_to", obj="B", license="unknown", confidence=.4)
    add_fact(conn, **args, source_name="S1", source_url="https://example.org/1")
    add_fact(conn, **args, source_name="S2", source_url="https://example.org/2")
    rows = query_facts(conn, status="candidate")
    assert len(rows) == 2
    assert {r["source_name"] for r in rows} == {"S1", "S2"}

def test_validation_requires_provenance_and_safe_confidence():
    with pytest.raises(ValueError):
        validate_fact("A", "related_to", "B", "", "https://example.org", "unknown", .5)
    with pytest.raises(ValueError):
        validate_fact("A", "related_to", "B", "S", "https://example.org", "unknown", 1.1)
    with pytest.raises(ValueError):
        validate_fact("A", "Related To", "B", "S", "https://example.org", "unknown", .5)

def test_bad_source_url_rejected():
    with pytest.raises(ValueError):
        add_fact(sqlite3.connect(":memory:"), subject="A", relation="r", obj="B",
                 source_name="S", source_url="javascript:alert(1)")

def test_schema_does_not_change_documents_table(conn):
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "documents" not in names
    assert {"structured_entities", "structured_facts", "structured_fact_sources"} <= names
