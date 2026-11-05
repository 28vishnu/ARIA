from brain.knowledge.answer_composer import AnswerComposer


def evidence(title, content, source="wikipedia", url="https://en.wikipedia.org/wiki/Test"):
    return {
        "title": title,
        "content": content,
        "source": source,
        "url": url,
        "confidence": 0.88,
        "evidence_score": 0.8,
    }


def test_solar_system_excludes_unrelated_evidence():
    composer = AnswerComposer()
    answer = composer.compose(
        "Explain our solar system.",
        [
            evidence("Solar System", "The Solar System includes the Sun and eight planets."),
            evidence("Photosynthesis", "Photosynthesis lets plants use sunlight to make food."),
            evidence("Computer", "A computer performs logical and arithmetic operations."),
        ],
    )
    assert "eight planets" in answer
    assert "Photosynthesis" not in answer
    assert "computer performs" not in answer


def test_gravity_everyday_example_is_added_without_llm():
    answer = AnswerComposer().compose(
        "What is gravity? Give an everyday example.",
        [evidence("Gravity", "Gravity is an interaction that draws material objects toward each other.")],
    )
    assert "gravity" in answer.lower()
    assert "drop a ball" in answer.lower()


def test_python_list_does_not_return_generic_python_article():
    answer = AnswerComposer().compose(
        "What is a Python list? Give an example.",
        [evidence("Python (programming language)", "Python is a high-level, general-purpose programming language.")],
    )
    assert "fruits = [\"apple\", \"banana\", \"mango\"]" in answer
    assert "docs.python.org/3/tutorial/datastructures.html" in answer


def test_simple_photosynthesis_is_simplified():
    answer = AnswerComposer().compose(
        "What is photosynthesis in simple words?",
        [evidence(
            "Photosynthesis",
            "Photosynthesis is a system of biological processes by which photopigment-bearing autotrophic organisms, such as most plants, algae and cyanobacteria, convert light energy—typically from sunlight—into the chemical energy necessary to fuel their metabolism."
        )],
    )
    assert "photopigment-bearing" not in answer
    assert "sunlight" in answer.lower()


def test_unrelated_evidence_is_not_used_as_fallback():
    answer = AnswerComposer().compose(
        "Explain our solar system.",
        [evidence("Computer", "A computer is a programmable machine for logical operations.")],
    )
    assert "couldn't find sufficiently relevant information" in answer.lower()
    assert "programmable machine" not in answer
