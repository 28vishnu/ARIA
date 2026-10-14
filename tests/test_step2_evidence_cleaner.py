import asyncio

from brain.knowledge.evidence_cleaner import (
    clean_evidence_text,
    hide_source_references,
    is_useful_evidence,
)
from brain.knowledge.knowledge_manager import KnowledgeManager
from brain.knowledge.online_knowledge import topic_from_question


def test_topic_normalization_removes_answer_directives():
    assert topic_from_question("What is quantum entanglement? And provide the source URL.") == "quantum entanglement"
    assert topic_from_question("Explain the Solar System and give an everyday example.") == "Solar System"
    assert topic_from_question("Compare RAM and storage with an everyday example.") == "RAM and storage"


def test_cleaner_removes_promotional_and_wikipedia_navigation_text():
    polluted = (
        "Explore Your membership perks Start exploring exclusive deals, expert advice and more Explore now "
        "Never Miss a Discovery Space news, cosmic updates and expert insights straight to your inbox. "
        "Choose your newsletters Sign Out Jump To: Quantum entanglement FAQs Have we proven quantum entanglement? "
        "Applications of quantum entanglement Key takeaway Additional resources Get the Space.com Newsletter "
        "Breaking space news, the latest updates on rocket launches, skywatching events and more! "
        "By submitting your information you agree to the Terms & Conditions and Privacy Policy and are aged 16 or over. "
        "Appearance From Wikipedia, the free encyclopedia Physics phenomenon Entanglement Energy level Hamiltonian "
        "Measurement Nonlocality Quantum number State Superposition Symmetry Tunnelling Uncertainty... "
        "Quantum entanglement is a physical phenomenon in which particles share a quantum state, "
        "so measurements of their properties are correlated even when the particles are separated."
    )
    cleaned = clean_evidence_text(polluted)
    assert "membership perks" not in cleaned.lower()
    assert "newsletter" not in cleaned.lower()
    assert "from wikipedia, the free encyclopedia" not in cleaned.lower()
    assert "Quantum entanglement is a physical phenomenon" in cleaned
    assert is_useful_evidence(cleaned)


def test_html_extraction_drops_navigation_and_keeps_article():
    html = (
        '<html><body><nav>Home Menu Subscribe</nav>'
        '<div class="newsletter-promo">Get the newsletter and sign up</div>'
        '<main><article><h1>Quantum entanglement</h1>'
        '<p>Quantum entanglement is a physical phenomenon in which particles share a quantum state.</p>'
        '<p>Measurements of their properties can be correlated even when the particles are separated.</p>'
        '</article></main><footer>All rights reserved</footer></body></html>'
    )
    cleaned = clean_evidence_text(html)
    assert "Quantum entanglement is a physical phenomenon" in cleaned
    assert "Subscribe" not in cleaned
    assert "newsletter" not in cleaned.lower()


def test_navigation_only_content_is_rejected():
    assert not is_useful_evidence(
        "Jump To: FAQs Key takeaway Additional resources Sign Out Choose your newsletters"
    )


def test_telegram_source_footer_is_hidden():
    answer = "Quantum entanglement links quantum states.\n\nSources:\n• Wikipedia — https://en.wikipedia.org/wiki/Quantum_entanglement"
    visible = hide_source_references(answer)
    assert "Quantum entanglement links quantum states." == visible
    assert "https://" not in visible
    assert hide_source_references(
        "A direct answer.\n\nSources: https://example.org/a · https://example.org/b"
    ) == "A direct answer."
    assert hide_source_references(
        "A direct answer.\n• Wikipedia — https://en.wikipedia.org/wiki/Example"
    ) == "A direct answer."
    assert hide_source_references("Read [the article](https://example.org/article).") == "Read the article."


def test_solar_system_answer_includes_requested_everyday_example():
    from brain.knowledge.answer_composer import AnswerComposer
    answer = AnswerComposer().compose(
        "Explain the Solar System and give an everyday example.",
        [{
            "source": "wikipedia",
            "title": "Solar System",
            "url": "https://en.wikipedia.org/wiki/Solar_System",
            "content": "The Solar System includes the Sun and eight planets. The planets orbit the Sun because of gravity.",
            "confidence": 0.9,
        }],
    )
    assert "Everyday analogy" in answer
    assert "not attached to the Sun by strings" in answer


def test_search_tool_dictionary_contract_is_consumed_correctly():
    class FakeSearchTool:
        def __init__(self):
            self.query = None

        async def execute(self, query, context=None):
            self.query = query
            return {
                "success": True,
                "results": [{
                    "title": "Quantum entanglement",
                    "url": "https://example.org/quantum-entanglement",
                    "snippet": (
                        "Quantum entanglement is a physical phenomenon in which particles "
                        "share a quantum state, creating correlations between measurements."
                    ),
                }],
            }

    manager = KnowledgeManager(None, None, None)
    tool = FakeSearchTool()
    manager.web_search = tool
    results = asyncio.run(manager.search_web("What is quantum entanglement?"))
    assert tool.query == "quantum entanglement"
    assert len(results) == 1
    assert results[0]["url"] == "https://example.org/quantum-entanglement"
    assert results[0]["content_type"] == "search_excerpt"


def test_composer_rejects_biosphere_for_solar_system_question():
    from brain.knowledge.answer_composer import AnswerComposer
    answer = AnswerComposer().compose(
        "Explain the Solar System and give an everyday example.",
        [{
            "source": "wikipedia",
            "title": "Biosphere",
            "url": "https://en.wikipedia.org/wiki/Biosphere",
            "content": (
                "The biosphere, also called the ecosphere, is the worldwide sum of all ecosystems. "
                "Regarding energy, it is an open system, with photosynthesis capturing solar energy."
            ),
            "confidence": 0.9,
        }],
    )
    assert "Biosphere" not in answer
    assert "lamp in the middle of a room" not in answer
    assert "couldn't find sufficiently relevant information" in answer


def test_composer_accepts_exact_solar_system_topic_and_source_url():
    from brain.knowledge.answer_composer import AnswerComposer
    answer = AnswerComposer().compose(
        "Explain the Solar System and give an everyday example.",
        [{
            "source": "wikipedia",
            "title": "Solar System",
            "url": "https://en.wikipedia.org/wiki/Solar_System",
            "content": "The Solar System includes the Sun and eight planets. The planets orbit the Sun because of gravity.",
            "confidence": 0.9,
        }],
    )
    assert "Solar System includes the Sun" in answer
    assert "Everyday analogy" in answer
    assert "https://en.wikipedia.org/wiki/Solar_System" in answer
