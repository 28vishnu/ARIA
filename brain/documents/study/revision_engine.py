import logging

logger = logging.getLogger("aria")


class RevisionEngine:

    def __init__(self, document_memory):

        self.document_memory = document_memory

    def generate(
        self,
        document_name=None,
        min_importance=0.7,
    ):

        notes = []

        for memory in self.document_memory.memories:

            if document_name:

                if memory.document_name != document_name:
                    continue

            if memory.importance < min_importance:
                continue

            notes.append({

                "concept": memory.concept,

                "summary": memory.description,

                "page": memory.source_page,

            })

        logger.info(

            "[RevisionEngine] Generated %d revision notes",

            len(notes),

        )

        return notes
