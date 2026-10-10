import asyncio

from brain.knowledge.knowledge_manager import KnowledgeManager
from brain.knowledge.online_knowledge import store_search_evidence, topic_from_question
from brain.knowledge.open_knowledge import search


def test_topic_from_question_removes_answer_framing():
    assert topic_from_question("What is gravity?") == "gravity"
    assert topic_from_question("Explain photosynthesis in simple words.") == "photosynthesis"


def test_online_search_excerpt_is_persisted_and_searchable(tmp_path):
    db_path = str(tmp_path / "knowledge.sqlite3")
    evidence = [{
        "title": "Gravity",
        "url": "https://example.org/gravity",
        "content": (
            "Gravity is the force by which a planet or other body draws objects "
            "toward its center. On Earth it gives objects weight."
        ),
    }]
    result = store_search_evidence(db_path, evidence)
    assert result["processed"] == 1
    found = search(db_path, "gravity", limit=5)
    assert found
    assert found[0]["title"] == "Gravity"
    assert found[0]["url"] == "https://example.org/gravity"


def test_online_excerpt_store_rejects_non_http_and_tiny_snippets(tmp_path):
    db_path = str(tmp_path / "knowledge.sqlite3")
    result = store_search_evidence(db_path, [
        {"title": "Bad URL", "url": "file:///etc/passwd", "content": "A sufficiently long content excerpt that should not be stored."},
        {"title": "Too short", "url": "https://example.org/page", "content": "tiny"},
    ])
    assert result["accepted"] == 0
    assert result["processed"] == 0


def test_sufficiency_check_detects_missing_and_present_evidence():
    manager = KnowledgeManager(None, None, None)
    assert not manager._evidence_is_sufficient("What is gravity?", [])
    assert manager._evidence_is_sufficient("What is gravity?", [{
        "title": "Gravity",
        "content": "Gravity attracts objects with mass toward each other.",
        "confidence": 0.85,
    }])


def test_answer_uses_online_fallback_after_local_miss(monkeypatch):
    manager = KnowledgeManager(None, None, None)
    calls = {"online": 0, "compose": 0}

    async def retrieve(_session, _question):
        return []

    async def online(_question, try_wikimedia=True):
        calls["online"] += 1
        return [{
            "source": "web_search",
            "title": "Gravity",
            "url": "https://example.org/gravity",
            "content": "Gravity attracts objects with mass toward each other.",
            "confidence": 0.75,
            "relevance": 0.8,
        }]

    async def best_answer(_question, evidence):
        calls["compose"] += 1
        assert any(item.get("source") == "web_search" for item in evidence)
        return "Gravity attracts objects with mass toward each other. Source: https://example.org/gravity"

    monkeypatch.setattr(manager, "retrieve", retrieve)
    monkeypatch.setattr(manager, "_online_fallback", online)
    monkeypatch.setattr(manager, "best_answer", best_answer)

    result = asyncio.run(manager.answer("session-1", "What is gravity?"))
    assert "Gravity attracts" in result
    assert calls == {"online": 1, "compose": 1}


def test_sufficient_local_evidence_does_not_trigger_online(monkeypatch):
    manager = KnowledgeManager(None, None, None)
    async def retrieve(_session, _question):
        return [{
            "source": "wikipedia",
            "title": "Gravity",
            "url": "https://en.wikipedia.org/wiki/Gravity",
            "content": "Gravity is a fundamental interaction that attracts objects with mass.",
            "confidence": 0.9,
        }]
    async def online(*args, **kwargs):
        raise AssertionError("Online retrieval should not be needed.")
    async def best_answer(_question, _evidence):
        return "Gravity attracts objects with mass. Source: https://en.wikipedia.org/wiki/Gravity"
    monkeypatch.setattr(manager, "retrieve", retrieve)
    monkeypatch.setattr(manager, "_online_fallback", online)
    monkeypatch.setattr(manager, "best_answer", best_answer)
    result = asyncio.run(manager.answer("session-1", "What is gravity?"))
    assert "Gravity attracts" in result


def test_online_evidence_is_saved_to_durable_knowledge_store():
    class FakeStore:
        def __init__(self):
            self.records = []

        async def store(self, **kwargs):
            self.records.append(kwargs)
            return {"title": kwargs["title"]}

    manager = KnowledgeManager(None, None, None, knowledge_database=FakeStore())
    evidence = [{
        "title": "Gravity",
        "url": "https://example.org/gravity",
        "content": "Gravity attracts objects with mass toward each other in nature.",
    }]
    saved = asyncio.run(manager._persist_online_to_durable_store(evidence))
    assert saved == 1
    record = manager.knowledge_database.records[0]
    assert record["source"] == "web_search"
    assert record["metadata"]["url"] == "https://example.org/gravity"
    assert record["metadata"]["external_llm_used"] is False
