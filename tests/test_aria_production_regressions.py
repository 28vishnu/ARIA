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
    engine = ReasoningEngine()
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


def test_answer_composer_strips_source_request_from_topic():
    from brain.knowledge.answer_composer import AnswerComposer
    assert AnswerComposer._normalized_question("What is photosynthesis? Give me sources.") == "photosynthesis"


def test_conversation_manager_resolves_explain_that_from_last_calculation():
    from brain.conversation.conversation_manager import ConversationManager
    manager = object.__new__(ConversationManager)
    sessions = {
        "session-test": {
            "conversation_history": [{
                "user": "Calculate 1847 × 29 and show the result.",
                "assistant": "The answer is 53563, Sir.",
            }],
            "last_user_message": "Calculate 1847 × 29 and show the result.",
            "last_assistant_message": "The answer is 53563, Sir.",
        }
    }
    manager.sessions = sessions
    manager.get_session = lambda session_id: sessions.setdefault(session_id, {"conversation_history": []})
    result = manager.resolve_reference("session-test", "Explain that in one simple sentence")
    assert "previous calculation" in result.lower()
    assert "53563" in result


def test_core_clarifies_unspecified_obscure_fact_before_routing():
    core = object.__new__(CognitiveCore)
    core.knowledge_manager = KnowledgeManager(None, None, None)
    core._create_execution_id = lambda: "test-execution"

    async def unexpected(*args, **kwargs):
        raise AssertionError("vague prompt must return before retrieval/routing")

    core._is_compound_memory_request = lambda *args, **kwargs: False
    response = asyncio.run(core.process(
        "Give me a verifiable answer about a very obscure fact, with sources.",
        session_id="test-session",
        user_id="test-user",
        base_context={},
    ))
    assert "what topic" in str(response.data.get("response", "")).lower()
    assert response.source == "clarification"


def test_core_explains_resolved_calculation_followup_without_tool_routing():
    core = object.__new__(CognitiveCore)
    core.knowledge_manager = None
    core._create_execution_id = lambda: "test-execution"
    query = (
        "Explain the result of the previous calculation "
        "(Calculate 1847 × 29 and show the result.; result: The answer is 53563, Sir.) "
        "one simple sentence."
    )
    response = asyncio.run(core.process(
        query,
        session_id="test-session",
        user_id="test-user",
        base_context={},
    ))
    assert response.source == "deterministic_followup"
    assert "53,563" in response.data["response"]
    assert "1,847" in response.data["response"]
