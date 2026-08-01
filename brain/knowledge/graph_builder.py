import re
import logging

logger = logging.getLogger("aria")


class GraphBuilder:

    """
    Converts raw text into structured knowledge.
    """

    def __init__(self, knowledge_graph):

        self.graph = knowledge_graph

    async def learn(self, text: str):

        if not text:
            return

        await self.extract_patterns(text)

    async def extract_patterns(self, text):

        patterns = [

            (
                r"My name is ([A-Za-z ]+)",
                lambda m: (
                    m.group(1).strip(),
                    "is",
                    "User"
                )
            ),

            (
                r"I study at ([A-Za-z0-9 .&]+)",
                lambda m: (
                    "User",
                    "studies_at",
                    m.group(1).strip()
                )
            ),

            (
                r"I work at ([A-Za-z0-9 .&]+)",
                lambda m: (
                    "User",
                    "works_at",
                    m.group(1).strip()
                )
            ),

            (
                r"([A-Za-z ]+) is the capital of ([A-Za-z ]+)",
                lambda m: (
                    m.group(2).strip(),
                    "capital",
                    m.group(1).strip()
                )
            ),

            (
                r"I live in ([A-Za-z ]+)",
                lambda m: (
                    "User",
                    "lives_in",
                    m.group(1).strip()
                )
            ),

            (
                r"I have ([A-Za-z ]+) on ([A-Za-z]+)",
                lambda m: (
                    m.group(2).strip(),
                    "class",
                    m.group(1).strip()
                )
            ),

        ]

        for pattern, creator in patterns:

            for match in re.finditer(pattern, text, re.IGNORECASE):

                subject, relation, obj = creator(match)

                await self.graph.add_fact(
                    subject,
                    relation,
                    obj
                )

                logger.info(
                    "[GraphBuilder] %s %s %s",
                    subject,
                    relation,
                    obj,
                )