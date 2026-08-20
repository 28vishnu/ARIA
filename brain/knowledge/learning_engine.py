import logging
import re
from typing import Optional, Dict, Any

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
        self.statistics = {
            "learned": 0,
            "duplicates": 0,
            "updates": 0,
            "rejected": 0,
            "contradictions": 0,
            "documents": 0,
            "web_sources": 0,
            "conversations": 0,
            "concepts": 0,
            "relationships": 0,
        }

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

        existing = await self.database.search(
            text,
            limit=5,
        )

        if existing:
            best_match = existing[0]

            similarity = self._estimate_similarity(
                text,
                best_match.get("content", ""),
            )

            if similarity >= 0.90:
                self.statistics["duplicates"] += 1

                logger.info(
                    "[LearningEngine] Duplicate knowledge rejected: %s",
                    text[:100],
                )

                return best_match

            if similarity >= 0.65:
                self.statistics["updates"] += 1

                return await self._merge_knowledge(
                    existing=best_match,
                    new_content=text,
                    source=source,
                )

        title = self._generate_title(text)

        await self.database.store(
            title=title,
            content=text,
            source=source,
        )

        await self.builder.learn(text)

        self.learned_count += 1
        self.statistics["learned"] += 1

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

        record = await self.database.store(
            title=filename,
            content=summary,
            source="document",
            metadata={
                "filename": filename,
                "entities": entities or [],
                "learned_at": datetime.utcnow(),
            },
        )

        await self.builder.learn(summary)

        if entities:

            for entity in entities:

                await self.graph.add_entity(entity)

        self.learned_count += 1
        self.statistics["documents"] += 1

        logger.info(
            "[LearningEngine] Learned document %s",
            filename,
        )

        return record

    ############################################################

    async def learn_web(
        self,
        query,
        answer,
        metadata=None,
    ):
        """
        Learn information obtained from external sources.

        External information is stored as sourced knowledge rather
        than being treated as unquestionable truth.
        """

        if not query or not answer:
            return

        query = str(query).strip()
        answer = str(answer).strip()

        if not answer:
            return

        metadata = metadata or {}

        existing = await self.database.search(
            query,
            limit=5,
        )

        if existing:
            similarity = self._estimate_similarity(
                answer,
                existing[0].get("content", ""),
            )

            if similarity >= 0.90:
                self.statistics["duplicates"] += 1
                return existing[0]

        record = await self.database.store(
            title=query,
            content=answer,
            source="web",
            metadata={
                **metadata,
                "query": query,
                "learned_at": datetime.utcnow(),
            },
        )

        if self.builder:
            await self.builder.learn(answer)

        self.learned_count += 1
        self.statistics["web_sources"] += 1

        logger.info(
            "[LearningEngine] Learned web knowledge: %s",
            query,
        )

        return record

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
        self.statistics["concepts"] += 1

    ############################################################

    async def learn_relationships(
        self,
        text,
    ):
        """
        Extract and persist relationships without generating
        conversational output.
        """

        if not text or not self.builder:
            return

        result = await self.builder.learn(text)

        self.statistics["relationships"] += 1

        return result

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

    def _estimate_similarity(
        self,
        first: str,
        second: str,
    ) -> float:
        """
        Lightweight lexical similarity used before deeper
        semantic/vector evaluation.

        This is intentionally not the final intelligence layer.
        It prevents obvious duplicate knowledge from being stored.
        """

        first_words = {
            word.lower()
            for word in re.findall(r"\w+", first)
            if len(word) > 2
        }

        second_words = {
            word.lower()
            for word in re.findall(r"\w+", second)
            if len(word) > 2
        }

        if not first_words or not second_words:
            return 0.0

        intersection = first_words & second_words
        union = first_words | second_words

        return len(intersection) / len(union)

    ############################################################

    async def _merge_knowledge(
        self,
        existing: Dict[str, Any],
        new_content: str,
        source: str,
    ):
        """
        Merge new information into existing knowledge instead of
        blindly creating another record.
        """

        knowledge_id = existing.get("_id")

        if not knowledge_id:
            return await self.database.store(
                title=self._generate_title(new_content),
                content=new_content,
                source=source,
            )

        old_content = existing.get("content", "")

        if new_content.strip() == old_content.strip():
            self.statistics["duplicates"] += 1
            return existing

        merged_content = (
            f"{old_content}\n\n"
            f"[Additional information from {source}]\n"
            f"{new_content}"
        )

        await self.database.update(
            knowledge_id,
            {
                "content": merged_content,
                "summary": merged_content[:250],
                "source": source,
            },
        )

        await self.builder.learn(new_content)

        self.learned_count += 1
        self.statistics["updates"] += 1

        logger.info(
            "[LearningEngine] Knowledge updated: %s",
            existing.get("title", knowledge_id),
        )

        return existing

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

    ############################################################

    def statistics_summary(self) -> Dict[str, Any]:
        """
        Return learning telemetry for ARIA's internal monitoring.
        """

        return {
            **self.statistics,
            "learned_count": self.learned_count,
        }
