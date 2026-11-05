import logging

logger = logging.getLogger("aria")


class MCQGenerator:

    def __init__(self, document_memory):

        self.document_memory = document_memory

    def generate(
        self,
        document_name=None,
        limit=10,
    ):

        questions = []

        for memory in self.document_memory.memories:

            if document_name and memory.document_name != document_name:
                continue

            if not memory.description:
                continue

            questions.append({

                "question":
                    f"What is {memory.concept}?",

                "options": [

                    memory.description,

                    "None of the above",

                    "Insufficient information",

                    "Not related",

                ],

                "answer": 0,

                "page": memory.source_page,

            })

            if len(questions) >= limit:
                break

        logger.info(
            "[MCQGenerator] Generated %d MCQs",
            len(questions),
        )

        return questions
