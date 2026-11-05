from brain.knowledge.query_planner import plan_knowledge_query
from brain.knowledge.online_knowledge import topic_from_question


def test_basic_factual_query_is_compact():
    assert topic_from_question("What is quantum entanglement?") == "quantum entanglement"


def test_long_pasted_context_uses_final_question_for_search():
    document = ("The report describes network outages, retries, and database failures. " * 80)
    prompt = document + "\n\nQuestion: Why did the database connection pool exhaust?"
    result = plan_knowledge_query(prompt)
    assert "database connection pool exhaust" in result.casefold()
    assert len(result) <= 180


def test_question_with_sources_keeps_topic_not_formatting():
    assert topic_from_question("Explain photosynthesis in simple words and provide the source URL") == "photosynthesis"


def test_long_task_is_bounded_and_not_empty():
    prompt = "Explain " + "distributed systems consistency replication consensus " * 100
    result = plan_knowledge_query(prompt)
    assert result
    assert len(result) <= 180


def test_blank_input_stays_blank():
    assert plan_knowledge_query("  \n ") == ""
