from brain.knowledge.knowledge_manager import KnowledgeManager
from brain.knowledge.answer_composer import AnswerComposer


def test_ram_storage_comparison_has_deterministic_local_fact():
    fact = KnowledgeManager._local_foundational_knowledge(
        "Compare RAM and storage with an everyday example."
    )
    assert fact is not None
    assert fact["source"] == "local_foundational_knowledge"
    assert "temporary working memory" in fact["content"]
    assert "bookshelf" in fact["content"]
    assert fact["external_llm_synthesis"] is False


def test_example_phrase_does_not_pollute_comparison_topic():
    normalized = AnswerComposer._normalized_question(
        "Compare RAM and storage with an everyday example."
    )
    assert "everyday" not in normalized
    assert "example" not in normalized
    assert "ram" in normalized
    assert "storage" in normalized


def test_ram_storage_answer_composes_without_unrelated_evidence():
    fact = KnowledgeManager._local_foundational_knowledge(
        "Compare RAM and storage with an everyday example."
    )
    answer = AnswerComposer().compose(
        "Compare RAM and storage with an everyday example.", [fact]
    )
    assert "RAM" in answer
    assert "storage" in answer.lower()
    assert "bookshelf" in answer.lower()
