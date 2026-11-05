import logging
from difflib import SequenceMatcher

logger = logging.getLogger("aria")


class SemanticSearch:

    def __init__(self, document_memory):

        self.document_memory = document_memory

    def similarity(
        self,
        a: str,
        b: str,
    ) -> float:

        return SequenceMatcher(
            None,
            a.lower(),
            b.lower(),
        ).ratio()

    def search(
        self,
        query: str,
        limit: int = 5,
    ):

        scored = []

        for memory in self.document_memory.memories:

            score = max(
                self.similarity(query, memory.concept),
                self.similarity(query, memory.description),
            )

            if score >= 0.35:

                scored.append(
                    (
                        score,
                        memory,
                    )
                )

        scored.sort(
            key=lambda x: x[0],
            reverse=True,
        )

        logger.info(
            "[SemanticSearch] Found %d matches",
            len(scored),
        )

        return [
            memory
            for score, memory in scored[:limit]
        ]
