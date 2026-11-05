"""Offline end-to-end checks for ARIA's evidence retrieval and answer path."""
import asyncio

from brain.knowledge.answer_composer import AnswerComposer
from brain.knowledge.knowledge_manager import KnowledgeManager
from brain.knowledge.retrieval_coordinator import RetrievalCoordinator


def test_coordinator_uses_local_evidence_without_online_fallback():
    coordinator = RetrievalCoordinator()
    calls = {"local": 0, "online": 0}

    async def local(query):
        calls["local"] += 1
        return [{"title": "Python lists", "content": "Python lists are ordered collections.", "url": "https://docs.python.org/3/tutorial/datastructures.html"}]

    async def online(query):
        calls["online"] += 1
        return []

    result = asyncio.run(coordinator.retrieve(
        "What are Python lists?", local, online,
        lambda evidence, query: bool(evidence),
    ))
    assert result.local_evidence_count == 1
    assert result.used_online is False
    assert calls == {"local": 1, "online": 0}


def test_coordinator_falls_back_to_online_when_local_evidence_is_insufficient():
    coordinator = RetrievalCoordinator()
    received = []

    async def local(query):
        return [{"title": "Unrelated", "content": "An unrelated document."}]

    async def online(query):
        received.append(query)
        return [{"title": "Python lists", "content": "Python lists are ordered collections.", "url": "https://docs.python.org/3/tutorial/datastructures.html"}]

    result = asyncio.run(coordinator.retrieve(
        "What are Python lists?", local, online,
        lambda evidence, query: False,
    ))
    assert result.used_online is True
    assert result.evidence[0]["url"].startswith("https://docs.python.org/")
    assert received == ["Python lists"]
    # Irrelevant local snippets must not leak into the final evidence set.
    assert all(item.get("title") != "Unrelated" for item in result.evidence)


def test_answer_composer_preserves_source_attribution():
    composer = AnswerComposer()
    answer = composer.compose("What is Python lists?", [{
        "title": "Python lists",
        "content": "Python lists are ordered, mutable collections that store multiple items.",
        "source": "Python documentation",
        "url": "https://docs.python.org/3/tutorial/datastructures.html",
        "verified": True,
    }])
    assert "Python lists" in answer
    assert "https://docs.python.org/3/tutorial/datastructures.html" in answer


def test_knowledge_manager_answer_returns_grounded_local_answer(monkeypatch, tmp_path):
    manager = KnowledgeManager(None, None, None)
    evidence = [{
        "title": "Python lists",
        "content": "Python lists are ordered, mutable collections that store multiple items.",
        "source": "Python documentation",
        "url": "https://docs.python.org/3/tutorial/datastructures.html",
        "verified": True,
        "confidence": 0.98,
    }]

    async def retrieve(session_id, question):
        return evidence

    async def no_llm(question, records, draft):
        return None

    async def no_online(question, try_wikimedia=True):
        raise AssertionError("online fallback should not be called for sufficient local evidence")

    monkeypatch.setattr(manager, "retrieve", retrieve)
    monkeypatch.setattr(manager, "_requires_fresh_online_evidence", lambda question: False)
    monkeypatch.setattr(manager, "_evidence_is_sufficient", lambda question, records: True)
    monkeypatch.setattr(manager, "_llm_synthesize_from_evidence", no_llm)
    monkeypatch.setattr(manager, "_online_fallback", no_online)
    monkeypatch.setattr(manager, "_save_local_answer_cache", lambda *args, **kwargs: None)

    answer = asyncio.run(manager.answer("test-session", "What are Python lists?"))
    assert answer
    assert "Python lists" in answer
    assert "https://docs.python.org/3/tutorial/datastructures.html" in answer
