import logging

logger = logging.getLogger("aria")


class StudyEngine:

    def __init__(
        self,
        semantic_search,
        document_memory,
    ):

        self.semantic_search = semantic_search
        self.document_memory = document_memory

    def explain(
        self,
        topic: str,
    ):

        knowledge = self.semantic_search.search(
            topic,
            limit=5,
        )

        if not knowledge:

            return {
                "found": False,
                "message": "No knowledge found.",
            }

        return {
            "found": True,
            "topic": topic,
            "results": knowledge,
        }

    def summarize_document(
        self,
        document_name,
    ):

        summaries = []

        for memory in self.document_memory.memories:

            if memory.document_name == document_name:

                summaries.append(memory)

        return summaries

    def list_topics(
        self,
        document_name,
    ):

        topics = []

        for memory in self.document_memory.memories:

            if memory.document_name == document_name:

                topics.append(memory.concept)

        return sorted(
            set(topics)
        )
