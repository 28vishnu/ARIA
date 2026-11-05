import logging
import asyncio
from datetime import datetime
from typing import Dict, Any

logger = logging.getLogger("aria")


class ContextBuilder:
    """
    Builds ARIA's global context before every request.

    This collects everything ARIA currently knows so every  
    subsystem works with the same understanding.  

    It does NOT call any LLM.  
    """

    def __init__(
        self,
        state_manager,
        world_model,
        memory_router,
        knowledge_graph,
        knowledge_database,
        learning_engine,
    ):
        self.state_manager = state_manager
        self.world_model = world_model
        self.memory_router = memory_router
        self.knowledge_graph = knowledge_graph
        self.knowledge_database = knowledge_database
        self.learning_engine = learning_engine

    async def build(
        self,
        session_id: str,
        query: str,
    ) -> Dict[str, Any]:

        # -----------------------------------------  
        # Current session state  
        # -----------------------------------------  

        state = self.state_manager.get_state(session_id)

        # -----------------------------------------  
        # Working memory  
        # -----------------------------------------  

        working_memory = self.memory_router.snapshot()

        # -----------------------------------------  
        # Parallel Retrieval (Long-term memory, Graph, Knowledge, World)
        # -----------------------------------------  

        memories_task = self.memory_router.recall(query)

        graph_task = self.knowledge_graph.search(query)

        knowledge_task = self.knowledge_database.search(query)

        world_task = asyncio.to_thread(
            self.world_model.search,
            query,
        )

        memories, graph, knowledge, world = await asyncio.gather(
            memories_task,
            graph_task,
            knowledge_task,
            world_task,
        )

        # -----------------------------------------  
        # Knowledge Graph Summary  
        # -----------------------------------------  

        graph_summary = await self.knowledge_graph.summary()

        # -----------------------------------------  
        # Context Construction  
        # -----------------------------------------  

        context = {

            "query": query,

            "working_memory": working_memory,

            "long_term_memory": memories,

            "world_model": world,

            "knowledge_graph": graph,

            "graph_summary": graph_summary,

            "context_knowledge": knowledge,

            "active": self.world_model.active,

            "session": self.world_model.session,

            "tasks": self.world_model.tasks,

            "goals": self.world_model.goals,

            "preferences": self.world_model.preferences,

            "plans": self.world_model.long_term_plans,

            "habits": self.world_model.habits,

            "routines": self.world_model.routines,

            "skills": self.world_model.user_skills,

            "interests": self.world_model.interests,

            "brain": {

                "memory_loaded": len(memories),

                "graph_loaded": len(graph),

                "knowledge_loaded": bool(knowledge),

                "active_document": self.world_model.active.get("document"),

            },

            "context_time": datetime.utcnow(),

            "context_scores": {

                "memory": len(memories),

                "graph": len(graph),

                "knowledge": 1 if knowledge else 0,

            },

        }

        logger.info(
            "[ContextBuilder] Built global context."
        )

        return context
