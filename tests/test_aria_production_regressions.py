import asyncio

from brain.tools.calculator_tool import CalculatorTool, normalize_expression
from skills.calculator import CalculatorSkill, _normalize_expression as normalize_skill_expression
from brain.core.cognitive_core import CognitiveCore
from brain.knowledge.knowledge_manager import KnowledgeManager
from brain.knowledge.learning_engine import LearningEngine
from brain.knowledge.knowledge_database import KnowledgeDatabase
from brain.reasoning.reasoning_engine import ReasoningEngine


def test_calculator_normalizes_unicode_multiplication_and_trailing_request():
    assert normalize_expression("Calculate 1847 × 29 and show the result.") == "1847 * 29"


def test_calculator_tool_computes_arithmetic_safely():
    tool = CalculatorTool()
    result = asyncio.run(tool.execute("Calculate 1847 × 29 and show the result.", {}))
    assert result["success"] is True
    assert result["result"] == 53563


def test_calculator_rejects_python_code():
    tool = CalculatorTool()
    result = asyncio.run(tool.execute("__import__('os').system('echo bad')", {}))
    assert result["success"] is False


def test_calculator_is_selected_for_unicode_multiplication():
    tool = CalculatorTool()
    assert asyncio.run(tool.can_handle("Calculate 1847 × 29 and show the result.", {})) >= 0.9


def test_deterministic_capability_override_routes_calculation():
    core = object.__new__(CognitiveCore)
    decision = {"intent": "chat", "route": "chat", "action": "chat", "use_tools": False, "required_tools": []}
    result = core._apply_deterministic_capability_overrides("Calculate 1847 × 29 and show the result.", decision)
    assert result["intent"] == "calculation"
    assert result["use_tools"] is True
    assert "calculator" in result["required_tools"]


def test_unspecified_obscure_fact_request_asks_for_subject_before_search():
    manager = KnowledgeManager(None, None, None)
    assert manager._is_unspecified_fact_request("Give me a verifiable answer about a very obscure fact, with sources.")
    assert not manager._is_unspecified_fact_request("Give me an obscure fact about tardigrades with sources.")


def test_learning_engine_rejects_generic_fact_prompt_as_knowledge():
    assert LearningEngine._is_untrusted_failure_or_wrapper("Give me a verifiable answer about a very obscure fact, with sources.")


def test_database_rejects_generic_fact_prompt_as_knowledge():
    assert KnowledgeDatabase._is_rejected_learning_payload("Give me a verifiable answer", "Give me a verifiable answer about a very obscure fact, with sources.")


def test_followup_resolves_to_previous_calculation():
    engine = object.__new__(ReasoningEngine)
    result = asyncio.run(engine.resolve_references(
        "Explain that in one simple sentence.",
        {"conversation": {"conversation_history": [{
            "user": "Calculate 1847 × 29 and show the result.",
            "assistant": "53,563",
        }] }},
    ))
    assert "previous calculation" in result.lower()
    assert "1847 × 29" in result


def test_answer_composer_removes_timestamp_prefixes():
    from brain.knowledge.answer_composer import AnswerComposer
    sentences = AnswerComposer._sentences("[6:25] Knowing the topic matters. [6:32] RAM stores temporary data.")
    assert all(not sentence.startswith("[6:") for sentence in sentences)
    assert any("Knowing the topic matters" in sentence for sentence in sentences)


def test_live_calculator_skill_computes_unicode_multiplication():
    skill = CalculatorSkill()
    result = asyncio.run(skill.execute("Calculate 1847 × 29 and show the result.", {}))
    assert result.success is True
    assert result.data["result"] == 53563


def test_live_calculator_skill_strips_result_suffix():
    assert normalize_skill_expression("Calculate 1847 × 29 and show the result.") == "1847 * 29"


def test_unspecified_fact_request_returns_clarification_without_retrieving():
    manager = KnowledgeManager(None, None, None)
    async def unexpected_retrieve(*args, **kwargs):
        raise AssertionError("vague prompt should not trigger retrieval")
    manager.retrieve = unexpected_retrieve
    response = asyncio.run(manager.answer(
        "session-test",
        "Give me a verifiable answer about a very obscure fact, with sources.",
    ))
    assert "what topic" in response.lower()
