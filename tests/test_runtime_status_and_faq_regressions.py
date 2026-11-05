"""Regression tests for deterministic FAQs and live runtime-status responses."""
import re

from brain.knowledge.answer_composer import AnswerComposer


def test_python_lists_and_tuples_faq_works_without_retrieved_evidence():
    answer = AnswerComposer().compose(
        "What is the difference between Python lists and tuples? Give a simple example of each.",
        [],
    )
    assert "lists are mutable" in answer
    assert "tuples are immutable" in answer
    assert "numbers = [1, 2, 3]" in answer
    assert "point = (1, 2, 3)" in answer
    assert "docs.python.org" in answer


def test_unknown_question_still_fails_closed_without_evidence():
    answer = AnswerComposer().compose("Explain an obscure unknown topic", [])
    assert "couldn't find sufficiently relevant information" in answer.casefold()


def test_runtime_status_trigger_terms_are_present_in_source():
    # This guards the deterministic pre-routing status branch against removal.
    from pathlib import Path
    source = Path("brain/core/cognitive_core.py").read_text(encoding="utf-8")
    assert 'source="runtime_status"' in source
    assert "Not verified by this response" in source
