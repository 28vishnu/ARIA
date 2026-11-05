import asyncio
import sqlite3
from pathlib import Path

import pytest

from brain.knowledge.knowledge_manager import KnowledgeManager
from brain.knowledge.structured_facts import initialize_schema, add_fact


class EmptyDatabase:
    async def retrieve(self, question):
        return []


@pytest.fixture
def manager(tmp_path, monkeypatch):
    db = tmp_path / "aria.sqlite3"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    initialize_schema(conn)
    add_fact(
        conn,
        subject="Japan",
        relation="capital",
        obj="Tokyo",
        source_name="Test source",
        source_url="https://example.org/japan",
        license="CC0",
        evidence="A verified test evidence excerpt.",
        confidence=0.99,
        status="verified",
    )
    add_fact(
        conn,
        subject="France",
        relation="capital",
        obj="Paris",
        source_name="Test source",
        source_url="https://example.org/france",
        license="CC0",
        confidence=0.99,
        status="candidate",
    )
    conn.close()
    monkeypatch.setenv("ARIA_OPEN_KNOWLEDGE_DB", str(db))
    obj = KnowledgeManager(None, None, None, knowledge_database=EmptyDatabase())
    return obj, db


def test_verified_structured_facts_enter_database_retrieval(manager):
    obj, _ = manager
    results = asyncio.run(obj.search_database("What is the capital of Japan?"))
    structured = [item for item in results if item.get("source") == "structured_facts"]
    assert len(structured) == 1
    assert "Japan capital Tokyo" in structured[0]["content"]
    assert structured[0]["url"] == "https://example.org/japan"
    assert structured[0]["verified"] is True


def test_candidate_facts_are_not_returned(manager):
    obj, _ = manager
    results = asyncio.run(obj.search_structured_facts("capital France Paris"))
    assert all("France" not in item.get("content", "") for item in results)


def test_missing_database_is_not_created(tmp_path, monkeypatch):
    missing = tmp_path / "does-not-exist.sqlite3"
    monkeypatch.setenv("ARIA_OPEN_KNOWLEDGE_DB", str(missing))
    obj = KnowledgeManager(None, None, None)
    assert asyncio.run(obj.search_structured_facts("capital Japan")) == []
    assert not missing.exists()


def test_missing_schema_returns_empty_without_creating_tables(tmp_path, monkeypatch):
    db = tmp_path / "plain.sqlite3"
    sqlite3.connect(db).close()
    monkeypatch.setenv("ARIA_OPEN_KNOWLEDGE_DB", str(db))
    obj = KnowledgeManager(None, None, None)
    assert asyncio.run(obj.search_structured_facts("capital Japan")) == []
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []
    conn.close()
