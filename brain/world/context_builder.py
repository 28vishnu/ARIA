import logging
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
    ):

        self.state_manager = state_manager
        self.world_model = world_model
        self.memory_router = memory_router
        self.knowledge_graph = knowledge_graph

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
        # Long-term memory
        # -----------------------------------------

        memories = await self.memory_router.get_relevant_memories(query)

        # -----------------------------------------
        # World Model
        # -----------------------------------------

        world = self.world_model.snapshot()

        # -----------------------------------------
        # Knowledge Graph
        # -----------------------------------------

        graph = self.knowledge_graph.snapshot()

        context = {

            "query": query,

            "state": state,

            "working_memory": working_memory,

            "long_term_memory": memories,

            "world_model": world,

            "knowledge_graph": graph,

            "active_document":
                state.get("current_document"),

            "document_active":
                state.get("active_document", False),

            "current_goal":
                state.get("current_goal"),

            "current_project":
                state.get("current_project"),

            "user":
                state.get("user_profile", {}),

        }

        logger.info(
            "[ContextBuilder] Built global context."
        )

        return context