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
        memory_engine,
        knowledge_graph,
        graph_builder,
        llm_router=None,
        event_bus=None,
    ):

        self.database = knowledge_database
        self.memory = memory_engine
        self.graph = knowledge_graph
        self.builder = graph_builder
        self.llm_router = llm_router
        self.event_bus = event_bus
        self.learned_count = 0

    ############################################################

    async def learn(
        self,
        text: str,
        source="conversation",
    ):

        if not text:
            return

        text = text.strip()

        if not self._should_learn(text):
            return

        existing = await self.database.search(text)

        if existing:
            return

        title = self._generate_title(text)

        await self.database.store(
            title=title,
            content=text,
            source=source,
        )

        await self.builder.learn(text)

        self.learned_count += 1

        logger.info(
            "[LearningEngine] Learned: %s",
            title,
        )

    ############################################################

    async def learn_document(
        self,
        filename,
        summary,
        entities=None,
    ):

        if not summary:
            return

        await self.database.store(
            title=filename,
            content=summary,
            source="document"
        )

        await self.builder.learn(summary)

        if entities:

            for entity in entities:

                await self.graph.add_entity(entity)

        self.learned_count += 1

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

        await self.database.store(
            title=query,
            content=answer,
            source="web"
        )

        await self.builder.learn(answer)

        self.learned_count += 1

    ############################################################

    async def learn_fact(
        self,
        subject,
        relation,
        value,
    ):

        if self.graph:

            await self.graph.add_fact(
                subject,
                relation,
                value,
            )

    ############################################################

    async def learn_from_memory(
        self,
        memory,
    ):

        if not memory:
            return

        text = f"{memory.get('key')} : {memory.get('value')}"

        await self.learn(
            text,
            source="memory"
        )

    ############################################################

    async def learn_chat(
        self,
        user,
        assistant,
    ):

        text = user + "\n" + assistant

        await self.learn(
            text,
            source="conversation"
        )

    ############################################################

    async def learn_concepts(
        self,
        text,
    ):

        if self.llm_router is None:
            return

        concepts = await self.llm_router.extract_concepts(text)

        if not concepts:
            return

        for concept in concepts:

            await self.database.store(

                title=concept,

                content=text,

                source="concept"
            )

        self.learned_count += 1

    ############################################################

    async def learn_relationships(
        self,
        text,
    ):

        if self.builder:

            await self.builder.learn(text)

    ############################################################

    async def learn_profile(
        self,
        profile,
    ):

        if not profile:
            return

        for key, value in profile.items():

            await self.graph.add_fact(

                "User",

                key,

                value
            )

    ############################################################

    async def remember_document(
        self,
        filename,
        summary,
    ):

        await self.memory.process_and_store(
            summary
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

    def _should_learn(
        self,
        text,
    ):

        if self._is_small_talk(text):
            return False

        if len(text) < 20:
            return False

        return True

    ############################################################

    def _generate_title(
        self,
        text,
    ):

        words = re.findall(r"\w+", text)

        if not words:
            return "Knowledge"

        return " ".join(words[:6])
