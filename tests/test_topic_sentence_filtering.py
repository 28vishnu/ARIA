from brain.knowledge.answer_composer import AnswerComposer


def record(title, content, source="wikipedia", url="https://en.wikipedia.org/wiki/Test"):
    return {
        "title": title,
        "content": content,
        "source": source,
        "url": url,
        "confidence": 0.9,
        "evidence_score": 0.8,
        "verified": True,
    }


def test_photosynthesis_does_not_import_unrelated_biosphere_sentence():
    answer = AnswerComposer().compose(
        "What is photosynthesis?",
        [
            record(
                "Photosynthesis",
                "Photosynthesis is the process plants use to convert sunlight into chemical energy. "
                "Plants use this energy to make sugars from water and carbon dioxide.",
            ),
            record(
                "Photosynthesis and the biosphere",
                "The biosphere is the worldwide sum of all ecosystems. "
                "Chlorophyll is a green pigment found in plants and algae. "
                "Photosynthesis uses chlorophyll to absorb light energy.",
                url="https://example.org/photosynthesis-context",
            ),
        ],
    )
    assert "convert sunlight into chemical energy" in answer
    assert "worldwide sum of all ecosystems" not in answer
    assert "Photosynthesis uses chlorophyll to absorb light energy" in answer


def test_ram_storage_comparison_keeps_both_concepts_and_example():
    answer = AnswerComposer().compose(
        "Compare RAM and storage with an everyday example.",
        [
            record(
                "RAM vs Storage",
                "RAM is temporary working memory used by active programs. "
                "Storage keeps files and applications when the device is powered off. "
                "RAM is like desk space, while storage is like a bookshelf.",
                source="local_foundational_knowledge",
            ),
            record(
                "General computing",
                "A computer performs calculations. Storage devices retain saved files. "
                "RAM provides working memory for active tasks.",
                url="https://example.org/computing",
            ),
        ],
    )
    assert "RAM" in answer
    assert "Storage" in answer
    assert "bookshelf" in answer
    assert "performs calculations" not in answer


def test_solar_system_keeps_relevant_primary_answer_and_analogy():
    answer = AnswerComposer().compose(
        "Explain the Solar System and give an everyday example.",
        [
            record(
                "Solar System",
                "The Solar System consists of the Sun and objects held in orbit by its gravity. "
                "It includes eight planets, including Earth.",
            ),
            record(
                "Solar System overview",
                "The biosphere is the worldwide sum of all ecosystems. "
                "The Solar System includes planets that orbit the Sun.",
                url="https://example.org/solar-system",
            ),
        ],
    )
    assert "eight planets" in answer
    assert "lamp in the middle of a room" in answer
    assert "worldwide sum of all ecosystems" not in answer


def test_quantum_entanglement_keeps_source_relevant_and_rejects_unrelated_sentence():
    answer = AnswerComposer().compose(
        "What is quantum entanglement? And provide the source URL.",
        [
            record(
                "Quantum entanglement",
                "Quantum entanglement is a physical phenomenon in which particles share a quantum state. "
                "Measurements of entangled particles show correlations that cannot be explained by classical physics.",
            ),
            record(
                "Quantum entanglement and physics",
                "Quantum entanglement creates correlations between measurements on linked quantum systems. "
                "The solar system contains eight planets orbiting the Sun.",
                url="https://example.org/quantum-entanglement",
            ),
        ],
    )
    assert "share a quantum state" in answer
    assert "cannot be explained by classical physics" in answer
    assert "eight planets orbiting the Sun" not in answer
    assert "https://" in answer
