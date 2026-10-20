from pathlib import Path

from brain.knowledge.open_knowledge import read_topics_file


def test_core_topic_catalog_is_broad_and_unique():
    path = Path(__file__).parents[1] / "brain" / "knowledge" / "core_topics.txt"
    topics = read_topics_file(str(path))
    normalized = [topic.casefold() for topic in topics]

    assert len(topics) >= 700
    assert len(normalized) == len(set(normalized))
    assert all(topic.strip() for topic in topics)


def test_core_topic_catalog_covers_major_domains():
    path = Path(__file__).parents[1] / "brain" / "knowledge" / "core_topics.txt"
    topics = {topic.casefold() for topic in read_topics_file(str(path))}

    required = {
        "python (programming language)",
        "machine learning",
        "linear algebra",
        "quantum mechanics",
        "electrical engineering",
        "world history",
        "open educational resources",
        "public health",
        "cybersecurity advisory",
    }
    assert required <= topics
