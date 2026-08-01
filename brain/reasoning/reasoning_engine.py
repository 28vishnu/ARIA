import logging
import asyncio
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

from brain.agents.agent_workflow import AgentWorkflow

logger = logging.getLogger("aria")


@dataclass
class ReasoningResult:
    """
    Represents the complete reasoning outcome and evidence package before execution.
    """

    goal: str
    action: str
    confidence: float
    evidence: list
    selected_agents: list
    plan: list
    retrieved_memory: list
    retrieved_knowledge: list
    graph_results: list
    world_state: dict
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Legacy compatibility fields for orchestrators
    primary_action: str = "chat"
    secondary_actions: List[str] = field(default_factory=list)
    reasoning: str = ""
    action_name: Optional[str] = None
    action_params: Dict[str, Any] = field(default_factory=dict)
    workflow: Optional[AgentWorkflow] = None


class ReasoningEngine:
    """
    ARIA's core reasoning layer.

    It analyzes context, builds comprehensive evidence across memory, knowledge,
    graph, and world models, and orchestrates multi-agent selection.
    """

    def __init__(
        self,
        agent_manager=None,
        planner=None,
        memory_router=None,
        knowledge_database=None,
        knowledge_graph=None,
        world_model=None,
        learning_engine=None,
        llm_router=None,
        action_manager=None,
    ):
        self.agent_manager = agent_manager
        self.planner = planner
        self.memory_router = memory_router
        self.knowledge_database = knowledge_database
        self.knowledge_graph = knowledge_graph
        self.world_model = world_model
        self.learning_engine = learning_engine
        self.llm_router = llm_router
        self.action_manager = action_manager

    async def understand_goal(
        self,
        context: Dict[str, Any],
    ) -> str:
        """
        Determine the primary user objective.
        """
        query = str(context.get("query", "")).strip().lower()

        if any(w in query for w in ["remember", "store", "save", "forget", "delete memory"]):
            return "remember" if "forget" not in query and "delete" not in query else "delete"
        if any(w in query for w in ["delete", "remove", "clear"]):
            return "delete"
        if any(w in query for w in ["search", "find", "look up", "what is", "who is", "when"]):
            return "search"
        if any(w in query for w in ["plan", "how to", "steps", "build", "create"]):
            return "plan"
        if any(w in query for w in ["run", "execute", "calculate"]):
            return "execute"
        
        return "answer"

    async def retrieve_context(
        self,
        query: str,
    ) -> Dict[str, List[Any]]:
        """
        Retrieve evidence across Memory, KnowledgeDB, KnowledgeGraph, and WorldModel in parallel.
        """
        memories_task = (
            self.memory_router.recall(query)
            if self.memory_router and hasattr(self.memory_router, "recall")
            else asyncio.sleep(0)
        )
        knowledge_task = (
            self.knowledge_database.search(query)
            if self.knowledge_database and hasattr(self.knowledge_database, "search")
            else asyncio.sleep(0)
        )
        graph_task = (
            self.knowledge_graph.search(query)
            if self.knowledge_graph and hasattr(self.knowledge_graph, "search")
            else asyncio.sleep(0)
        )
        world_task = (
            asyncio.to_thread(self.world_model.search, query)
            if self.world_model and hasattr(self.world_model, "search")
            else asyncio.sleep(0)
        )

        results = await asyncio.gather(
            memories_task,
            knowledge_task,
            graph_task,
            world_task,
            return_exceptions=True,
        )

        memories, knowledge, graph, world = [
            r if not isinstance(r, Exception) else [] for r in results
        ]

        return {
            "memories": memories if isinstance(memories, list) else [memories] if memories else [],
            "knowledge": knowledge if isinstance(knowledge, list) else [knowledge] if knowledge else [],
            "graph": graph if isinstance(graph, list) else [graph] if graph else [],
            "world": world if isinstance(world, dict) else {},
        }

    async def choose_agents(
        self,
        query: str,
        context: Dict[str, Any],
    ) -> List[Any]:
        """
        Score available agents and pick the best combination.
        """
        if not self.agent_manager or not hasattr(self.agent_manager, "agents"):
            return []

        selected = []
        try:
            if hasattr(self.agent_manager, "select_agent"):
                best_agent, score = await self.agent_manager.select_agent(query, context)
                if best_agent:
                    selected.append(best_agent)
            else:
                for agent in self.agent_manager.agents.values():
                    selected.append(agent)
        except Exception:
            logger.exception("[ReasoningEngine] Agent selection failed.")

        return selected

    async def reason(self, context: Dict[str, Any]) -> ReasoningResult:
        """
        Build complete evidence, establish confidence ranking, select agents,
        and structure the ReasoningResult.
        """
        query = str(context.get("query", "")).strip()

        # 1. Understand Goal
        goal = await self.understand_goal(context)

        # 2. Retrieve Evidence in Parallel
        retrieval = await self.retrieve_context(query)
        memories = retrieval["memories"]
        knowledge = retrieval["knowledge"]
        graph_results = retrieval["graph"]
        world_state = retrieval["world"]

        # 3. Confidence Ranking
        source_confidences = []
        if memories:
            source_confidences.append(("memory", 0.95))
        if knowledge:
            source_confidences.append(("knowledge", 0.91))
        if graph_results:
            source_confidences.append(("graph", 0.88))
        if world_state:
            source_confidences.append(("world", 0.85))

        best_source, confidence = max(source_confidences, key=lambda x: x[1]) if source_confidences else ("chat", 0.73)

        # 4. Multi-Agent Reasoning Selection
        selected_agents = await self.choose_agents(query, context)
        workflow = AgentWorkflow()
        for agent in selected_agents:
            workflow.add(agent)

        # 5. Determine Plan Automatically if Multi-step Required
        plan = []
        if goal == "plan" or len(query.split()) > 10:
            if self.planner and hasattr(self.planner, "create_plan"):
                try:
                    task_plan = await self.planner.create_plan(query, context)
                    if task_plan and hasattr(task_plan, "tasks"):
                        plan = task_plan.tasks
                except Exception:
                    logger.exception("[ReasoningEngine] Task planning failed.")

        evidence = memories + knowledge + graph_results

        # 6. Learning Trigger / Automatic Updates
        if self.learning_engine and answer := (knowledge[0] if knowledge else memories[0] if memories else None):
            try:
                if isinstance(answer, dict):
                    ans_text = answer.get("content") or str(answer)
                else:
                    ans_text = str(answer)
                await self.learning_engine.learn(ans_text, source=best_source)
                if self.knowledge_graph and hasattr(self.knowledge_graph, "add_fact"):
                    await self.knowledge_graph.add_fact(query, "derived_from", ans_text[:50])
                if self.world_model and hasattr(self.world_model, "add_timeline_event"):
                    self.world_model.add_timeline_event({"query": query, "source": best_source})
            except Exception:
                logger.exception("[ReasoningEngine] Automatic learning hook failed.")

        action = "chat"
        if goal == "remember" or goal == "delete":
            action = "memory_conversation"
        elif goal == "plan":
            action = "planner"

        logger.info(
            "[ReasoningEngine] Goal=%s Action=%s Confidence=%.2f EvidenceCount=%d",
            goal,
            action,
            confidence,
            len(evidence)
        )

        return ReasoningResult(
            goal=goal,
            action=action,
            confidence=confidence,
            evidence=evidence,
            selected_agents=selected_agents,
            plan=plan,
            retrieved_memory=memories,
            retrieved_knowledge=knowledge,
            graph_results=graph_results,
            world_state=world_state,
            metadata={
                "source": best_source,
                "response_depth": context.get("response", {}).get("depth", "normal"),
            },
            primary_action=action,
            reasoning=f"Resolved objective '{goal}' with confidence {confidence:.2f} using evidence from {best_source}.",
            workflow=workflow
        )
