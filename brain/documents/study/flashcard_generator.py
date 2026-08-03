import logging

logger = logging.getLogger("aria")


class FlashcardGenerator:

    def __init__(self, document_memory):

        self.document_memory = document_memory

    def generate(
        self,
        document_name=None,
        limit=20,
    ):

        flashcards = []

        for memory in self.document_memory.memories:

            if document_name:

                if memory.document_name != document_name:
                    continue

            if not memory.description:
                continue

            flashcards.append({

                "question": memory.concept,

                "answer": memory.description,

                "page": memory.source_page,

            })

            if len(flashcards) >= limit:
                break

        logger.info(

            "[FlashcardGenerator] Generated %d flashcards",

            len(flashcards),

        )

        return flashcards
