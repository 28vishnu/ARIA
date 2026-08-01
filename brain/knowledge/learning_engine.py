import logging
import re
from typing import Optional

logger = logging.getLogger("aria")


class LearningEngine:

    """
    Learns useful information automatically.

    Responsibilities:
    - Learn important facts from conversations
    - Learn from uploaded documents
    - Learn from web search results
    - Ignore greetings and useless chatter
    """

    def __init__(
        self,
        knowledge_database,
        memory_engine=None,
        knowledge_graph=None,
    ):

        self.knowledge_database = knowledge_database
        self.memory_engine = memory_engine
        self.knowledge_graph = knowledge_graph

    ############################################################

    async def learn(
        self,
        text: str,
        source="conversation",
    ):

        if not text:
            return

        text = text.strip()

        if len(text) < 25:
            return

        if self._is_small_talk(text):
            return

        title = self._generate_title(text)

        await self.knowledge_database.store(
            title=title,
            content=text,
            source=source,
        )

        logger.info(
            "[LearningEngine] Learned: %s",
            title,
        )

    ############################################################

    async def learn_document(
        self,
        filename,
        summary,
    ):

        if not summary:
            return

        await self.knowledge_database.store(
            title=filename,
            content=summary,
            source="document",
        )

        logger.info(
            "[LearningEngine] Learned document %s",
            filename,
        )

    ############################################################

    async def learn_web(
        self,
        query,
        answer,
    ):

        if not answer:
            return

        await self.knowledge_database.store(
            title=query,
            content=answer,
            source="web",
        )

    ############################################################

    async def learn_fact(
        self,
        subject,
        relation,
        value,
    ):

        if self.knowledge_graph:

            await self.knowledge_graph.add_fact(
                subject,
                relation,
                value,
            )

    ############################################################

    def _is_small_talk(
        self,
        text,
    ):

        text = text.lower()

        ignore = [

            "hi",
            "hello",
            "hey",
            "thanks",
            "thank you",
            "good morning",
            "good night",
            "bye",
            "ok",
            "okay",
            "cool",
            "yes",
            "no",

        ]

        return text in ignore

    ############################################################

    def _generate_title(
        self,
        text,
    ):

        words = re.findall(r"\w+", text)

        if not words:
            return "Knowledge"

        return " ".join(words[:6])