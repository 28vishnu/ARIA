"""Regression tests for false-positive local evidence sufficiency."""
import asyncio

from brain.knowledge.knowledge_manager import KnowledgeManager


def test_biosphere_record_is_not_sufficient_for_solar_system_question():
    manager = KnowledgeManager(None, None, None)
    assert not manager._evidence_is_sufficient(
        "Explain the Solar System and give an everyday example.",
        [{
            "source": "wikipedia",
            "title": "Biosphere",
            "content": (
                "The biosphere is the worldwide sum of all ecosystems. "
                "Photosynthesis captures solar energy and the biosphere is an open system."
            ),
            "confidence": 0.9,
        }],
    )


def test_solar_system_record_is_sufficient_for_solar_system_question():
    manager = KnowledgeManager(None, None, None)
    assert manager._evidence_is_sufficient(
        "Explain the Solar System and give an everyday example.",
        [{
            "source": "wikipedia",
            "title": "Solar System",
            "content": "The Solar System includes the Sun and eight planets orbiting it.",
            "confidence": 0.9,
        }],
    )


def test_unrelated_local_hit_triggers_online_fallback(monkeypatch):
    manager = KnowledgeManager(None, None, None)
    calls = {"online": 0}

    async def retrieve(_session, _question):
        return [{
            "source": "wikipedia",
            "title": "Biosphere",
            "content": "The biosphere is the worldwide sum of all ecosystems.",
            "confidence": 0.9,
        }]

    async def online(_question, try_wikimedia=True):
        calls["online"] += 1
        return [{
            "source": "web_search",
            "title": "Solar System",
            "url": "https://science.nasa.gov/solar-system/",
            "content": "The Solar System consists of the Sun and the objects that orbit it, including eight planets.",
            "confidence": 0.8,
            "relevance": 0.9,
        }]

    async def best_answer(_question, evidence):
        assert any("Solar System" in str(item.get("title")) for item in evidence)
        return "The Solar System includes the Sun and eight planets."

    monkeypatch.setattr(manager, "retrieve", retrieve)
    monkeypatch.setattr(manager, "_online_fallback", online)
    monkeypatch.setattr(manager, "best_answer", best_answer)

    result = asyncio.run(manager.answer("session-1", "Explain the Solar System and give an everyday example."))
    assert "eight planets" in result
    assert calls["online"] == 1
