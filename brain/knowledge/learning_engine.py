import logging
import re
from typing import Any, Optional

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
        text: Any,
        source="conversation",
        **kwargs,
    ):
        """
        Universal learning entry point.

        Accepts normal text as well as structured learning metadata.
        The engine converts structured input into learnable text rather
        than allowing dictionaries to reach string/regex operations.
        """

        # ---------------------------------------------------------
        # Normalize reflection / structured learning calls
        # ---------------------------------------------------------

        if text is None:
            return

        if kwargs:
            reflection = kwargs.get("reflection")

            if reflection:
                text = reflection
                source = "reflection"

        # ---------------------------------------------------------
        # Safely normalize structured data
        # ---------------------------------------------------------

        if isinstance(text, dict):
            parts = []

            for key, value in text.items():
                if value is None:
                    continue

                if isinstance(value, (dict, list, tuple, set)):
                    value = str(value)

                parts.append(f"{key}: {value}")

            text = "\n".join(parts)

        elif not isinstance(text, str):
            text = str(text)

        text = text.strip()

        if not text:
            return

        # ---------------------------------------------------------
        # Ignore useless conversation
        # ---------------------------------------------------------

        if not self._should_learn(text):
            return

        # ---------------------------------------------------------
        # Avoid duplicate knowledge
        # ---------------------------------------------------------

        existing = await self.database.search(text)

        if existing is not None:
            try:
                if len(existing) > 0:
                    return
            except TypeError:
                pass

        # ---------------------------------------------------------
        # Store learned knowledge
        # ---------------------------------------------------------

        title = self._generate_title(text)

        await self.database.store(
            title=title,
            content=text,
            source=source,
        )

        # ---------------------------------------------------------
        # Update knowledge graph
        # ---------------------------------------------------------

        if self.builder is not None:
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

        if not isinstance(summary, str):
            summary = str(summary)

        await self.database.store(
            title=str(filename),
            content=summary,
            source="document",
        )

        if self.builder is not None:
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
        """
        Convert a memory record into normalized learnable text.
        """

        if not memory:
            return

        if isinstance(memory, dict):
            key = memory.get("key")
            value = memory.get("value")

            text = f"{key}: {value}"

        else:
            text = str(memory)

        await self.learn(
            text,
            source="memory",
        )

    ############################################################

    async def learn_chat(
        self,
        user,
        assistant,
    ):
        """
        Learn from a completed conversation while safely handling
        structured assistant outputs.
        """

        if user is None and assistant is None:
            return

        user_text = (
            user
            if isinstance(user, str)
            else str(user or "")
        )

        assistant_text = (
            assistant
            if isinstance(assistant, str)
            else str(assistant or "")
        )

        text = (
            f"User: {user_text}\n"
            f"Assistant: {assistant_text}"
        )

        await self.learn(
            text,
            source="conversation",
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
