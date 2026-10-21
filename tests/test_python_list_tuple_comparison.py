from brain.knowledge.answer_composer import AnswerComposer


def test_python_list_tuple_comparison_answers_without_retrieved_evidence():
    answer = AnswerComposer().compose(
        "What is the difference between Python lists and tuples? Give a concise answer.",
        [],
    )
    assert "lists are mutable" in answer
    assert "tuples are immutable" in answer
    assert "TypeError" in answer
    assert "https://docs.python.org/3/tutorial/datastructures.html#tuples-and-sequences" in answer


def test_python_list_tuple_comparison_does_not_trigger_for_list_only_question():
    answer = AnswerComposer().compose("What is a Python list? Give an example.", [])
    assert "fruits = [\"apple\", \"banana\", \"mango\"]" in answer
    assert "tuples are immutable" not in answer
