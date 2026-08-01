import logging
from datetime import datetime
from brain.events.event_listener import EventListener

logger = logging.getLogger("aria")


class AutonomousLearning(EventListener):

    """
    Central automatic learning system.

    Every important event inside ARIA comes here.

    Nobody else stores knowledge directly.
    """

    def __init__(
        self,
        memory_engine,
        learning_engine,
        knowledge_database,
        knowledge_graph,
        world_model,
    ):

        self.memory = memory_engine
        self.learning = learning_engine
        self.database = knowledge_database
        self.graph = knowledge_graph
        self.world = world_model

        self.statistics = {

            "documents": 0,

            "chats": 0,

            "web": 0,

            "skills": 0,

            "plans": 0,

            "failures": 0,

            "success": 0,

        }

    # =========================================================
    # INDIVIDUAL PROCESSING METHODS
    # =========================================================

    async def process_chat(
        self,
        user,
        assistant,
    ):
        await self.memory.store_chat(
            {
                "user": user,
                "assistant": assistant,
            }
        )

        await self.learning.learn_chat(
            user,
            assistant,
        )

        await self.database.store(
            title="Conversation",
            content=user + "\n" + assistant,
            source="conversation",
        )

        if hasattr(self.graph, "learn"):
            await self.graph.learn(
                user + "\n" + assistant
            )

        if hasattr(self.world, "learn"):
            await self.world.learn(
                user,
                assistant,
            )

        self.statistics["chats"] += 1

    async def process_document(
        self,
        filename,
        summary,
    ):
        await self.learning.learn_document(
            filename,
            summary,
        )

        await self.memory.remember(
            summary
        )

        await self.database.store(
            title=filename,
            content=summary,
            source="document",
        )

        if hasattr(self.graph, "learn"):
            await self.graph.learn(summary)

        if hasattr(self.world, "learn_document"):
            await self.world.learn_document(
                filename,
                summary,
            )

        self.statistics["documents"] += 1

    async def process_web(
        self,
        query,
        answer,
    ):
        if hasattr(self.learning, "learn_web"):
            await self.learning.learn_web(query, answer)

        await self.database.store(
            title=query,
            content=answer,
            source="web",
        )

        if hasattr(self.graph, "learn"):
            await self.graph.learn(answer)

        if hasattr(self.memory, "remember"):
            await self.memory.remember(answer)

        if hasattr(self.world, "learn"):
            await self.world.learn(query, answer)

        self.statistics["web"] += 1

    async def process_skill(
        self,
        skill_name,
        result,
    ):
        content = f"Skill {skill_name} executed with result: {result}"
        await self.database.store(
            title=f"Skill: {skill_name}",
            content=content,
            source="skill",
        )

        if hasattr(self.memory, "remember"):
            await self.memory.remember(content)

        self.statistics["skills"] += 1

    async def process_plan(
        self,
        plan,
    ):
        content = str(plan)
        await self.database.store(
            title="Execution Plan",
            content=content,
            source="plan",
        )

        if hasattr(self.world, "add_goal"):
            self.world.add_goal("Latest Plan", {"plan": content})

        self.statistics["plans"] += 1

    async def process_profile(
        self,
        profile,
    ):
        profile_str = str(profile)
        if hasattr(self.memory, "store_profile"):
            await self.memory.store_profile(profile)

        await self.database.store(
            title="User Profile",
            content=profile_str,
            source="profile",
        )

        if hasattr(self.graph, "learn"):
            await self.graph.learn(profile_str)

        if hasattr(self.learning, "learn_profile"):
            await self.learning.learn_profile(profile)

    async def process_failure(
        self,
        query,
    ):
        await self.database.store(
            title="Knowledge Gap",
            content=query,
            source="unknown",
        )

        self.statistics["failures"] += 1

    async def process_success(
        self,
        query,
        answer,
    ):
        content = f"Query: {query}\nAnswer: {answer}"
        await self.database.store(
            title="Successful Interaction",
            content=content,
            source="success",
        )

        self.statistics["success"] += 1

    # =========================================================
    # MAINTENANCE & UTILITIES
    # =========================================================

    async def consolidate(
        self,
    ):
        pass

    def summary(
        self,
    ):
        return self.statistics

    # =========================================================
    # UNIVERSAL ENTRY POINT
    # =========================================================

    async def learn(
        self,
        source: str,
        **kwargs,
    ):
        if source == "chat":
            await self.process_chat(
                kwargs.get("user"),
                kwargs.get("assistant"),
            )

        elif source == "document":
            await self.process_document(
                kwargs.get("filename"),
                kwargs.get("summary"),
            )

        elif source == "web":
            await self.process_web(
                kwargs.get("query"),
                kwargs.get("answer"),
            )

        elif source == "skill":
            await self.process_skill(
                kwargs.get("skill_name"),
                kwargs.get("result"),
            )

        elif source == "profile":
            await self.process_profile(
                kwargs.get("profile"),
            )

        elif source == "plan":
            await self.process_plan(
                kwargs.get("plan"),
            )

        elif source == "failure":
            await self.process_failure(
                kwargs.get("query"),
            )

        elif source == "success":
            await self.process_success(
                kwargs.get("query"),
                kwargs.get("answer"),
            )

    # =========================================================
    # EVENT LISTENER HANDLER
    # =========================================================

    async def handle(self, event):

        await self.learn(

            source=event.type,

            **event.data,

        )
