from brain.knowledge.answer_composer import AnswerComposer


def ev(title, content, url="https://example.org/article", score=0.8):
    return {"title": title, "content": content, "source": "wikipedia", "url": url,
            "confidence": 0.9, "evidence_score": score}


def test_photosynthesis_does_not_use_biosphere_as_heading_or_include_unrelated_sentences():
    answer = AnswerComposer().compose("What is photosynthesis?", [
        ev("Biosphere", "The biosphere is the worldwide sum of all ecosystems. "
           "Regarding energy, it is an open system, with photosynthesis capturing solar energy. "
           "The biosphere is a closed system with regard to matter."),
        ev("Chlorophyll", "Chlorophyll is a green pigment found in plants. "
           "Those pigments are involved in oxygenic photosynthesis."),
    ])
    assert "couldn't find sufficiently relevant information" in answer.lower()
    assert "Biosphere" not in answer
    assert "worldwide sum of all ecosystems" not in answer


def test_solar_system_prefers_topic_title_and_excludes_image_captions():
    answer = AnswerComposer().compose("Explain the Solar System and give an everyday example.", [
        ev("Biosphere", "The biosphere includes ecosystems and photosynthesis captures solar energy.", score=0.99),
        ev("Solar System - Wikipedia", "The Solar System is the Sun and the objects that orbit it. "
           "Earth is one of eight planets. Solar system illustration © Example Artist. "
           "An illustration of our solar system."),
    ])
    assert answer.startswith("Solar System - Wikipedia")
    assert "eight planets" in answer
    assert "illustration" not in answer.lower()
    assert "lamp" in answer.lower()  # requested analogy is retained


def test_ram_storage_comparison_keeps_both_topics_and_analogy():
    answer = AnswerComposer().compose("Compare RAM and storage with an everyday example.", [
        ev("RAM vs Storage", "RAM is fast temporary working memory. Storage keeps files long term. "
           "RAM is like desk space; storage is like a bookshelf."),
    ])
    assert "temporary working memory" in answer
    assert "keeps files long term" in answer
    assert "bookshelf" in answer


def test_unrelated_article_with_no_topic_sentence_is_rejected():
    answer = AnswerComposer().compose("What is photosynthesis?", [
        ev("Biosphere", "The biosphere is the worldwide sum of all ecosystems. "
           "It is an open system with regard to energy."),
    ])
    assert "couldn't find sufficiently relevant information" in answer.lower()


def test_definition_in_generic_title_can_answer_topic_safely():
    answer = AnswerComposer().compose("What is photosynthesis?", [
        ev("Science glossary excerpt", "Photosynthesis is the process by which plants use light to make sugars.")
    ])
    assert answer.startswith("Photosynthesis")
    assert "plants use light to make sugars" in answer


def test_quantum_entanglement_uses_topic_article_over_incidental_mention():
    answer = AnswerComposer().compose("What is quantum entanglement?", [
        ev("Quantum entanglement", "Quantum entanglement is a physical phenomenon in which particles share a joint quantum state."),
        ev("Quantum mechanics overview", "Quantum mechanics describes matter and energy. The Solar System formed billions of years ago."),
    ])
    assert answer.startswith("Quantum entanglement")
    assert "joint quantum state" in answer
    assert "Solar System formed" not in answer
