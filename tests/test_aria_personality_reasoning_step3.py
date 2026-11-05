from personality.addressing import AddressingEngine
from brain.conversation.conversation_manager import ConversationManager


def test_addressing_is_consistently_respectful_by_default():
    engine = AddressingEngine()
    for context in ("normal", "technical", "security", "warning", "greeting", "casual", "unknown"):
        assert engine.get_address(context) == "Sir"


def test_explicit_valid_title_preference_is_respected():
    engine = AddressingEngine()
    assert engine.get_address(preferred="Commander") == "Commander"
    assert engine.get_address(preferred="not a title") == "Sir"


def make_manager_with_history(user, assistant):
    manager = object.__new__(ConversationManager)
    sessions = {
        "s": {
            "conversation_history": [{"user": user, "assistant": assistant}],
            "last_user_message": user,
            "last_assistant_message": assistant,
        }
    }
    manager.get_session = lambda session_id: sessions.setdefault(session_id, {"conversation_history": []})
    return manager


def test_calculation_followup_keeps_calculation_context():
    manager = make_manager_with_history(
        "Calculate 1847 × 29 and show the result.",
        "The answer is 53563, Sir.",
    )
    result = manager.resolve_reference("s", "Explain that in one simple sentence")
    assert "previous calculation" in result.lower()
    assert "53563" in result
    assert "one simple sentence" in result


def test_summarize_that_resolves_to_previous_answer():
    manager = make_manager_with_history("What is photosynthesis?", "Plants use light to convert carbon dioxide and water into sugars and oxygen.")
    result = manager.resolve_reference("s", "Summarize that")
    assert "previous answer" in result.lower()
    assert "photosynthesis" in result.lower()
    assert "convert carbon dioxide" in result


def test_give_an_example_resolves_to_previous_answer():
    manager = make_manager_with_history("Explain a Python list.", "A list stores an ordered collection of items.")
    result = manager.resolve_reference("s", "Give me an example")
    assert "previous answer" in result.lower()
    assert "Python list" in result


def test_followup_without_history_is_not_fabricated():
    manager = make_manager_with_history("", "")
    result = manager.resolve_reference("s", "Summarize that")
    assert result == "Summarize that"
