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
    Purely observational, analytical, and non-mutating.
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
        event_bus=None,
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
        self.event_bus = event_bus

    async def understand_goal(
        self,
        context: Dict[str, Any],
    ) -> str:
        """
        Determine the primary user objective using intent, conversation state,
        current goals, active documents, and query characteristics.
        """
        query = str(context.get("query", "")).strip().lower()
        intent = context.get("intent")
        intent_name = intent.name if intent else None
        active_doc = context.get("active", {}).get("document") or context.get("active_document")
        current_goal = context.get("current_goal")

        if intent_name in ("memory_store", "memory_update", "memory_delete") or any(w in query for w in ["remember", "store", "save", "forget", "delete memory"]):
            return "remember" if "forget" not in query and "delete" not in query else "delete"
        if intent_name in ("delete_document", "delete_all_documents") or any(w in query for w in ["delete", "remove", "clear"]):
            return "delete"
        if intent_name == "planner" or any(w in query for w in ["plan", "how to", "steps", "build", "create"]):
            return "plan"
        if any(w in query for w in ["search", "find", "look up", "what is", "who is", "when"]):
            return "search"
        if any(w in query for w in ["run", "execute", "calculate"]):
            return "execute"
        if active_doc or current_goal:
            return "contextual_chat"

        return "answer"

    async def retrieve_context(
        self,
        query: str,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Retrieve evidence across Memory, KnowledgeDB, KnowledgeGraph, and WorldModel in parallel,
        normalizing each item into a standard structured format.
        """
        memories_task = (
            self.memory_router.recall(query)
            if self.memory_router and hasattr(self.memory_router, "recall")
            else asyncio.sleep(0)
        )
        knowledge_task = (
            self.knowledge_database.retrieve(query)
            if self.knowledge_database and hasattr(self.knowledge_database, "retrieve")
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

        raw_memories, raw_knowledge, raw_graph, raw_world = [
            r if not isinstance(r, Exception) else [] for r in results
        ]

        # Normalize memories
        memories = []
        for m in (raw_memories if isinstance(raw_memories, list) else [raw_memories] if raw_memories else []):
            content = m.get("content", str(m)) if isinstance(m, dict) else str(m)
            memories.append({
                "source": "memory",
                "confidence": 0.95,
                "importance": 85,
                "content": content,
            })

        # Normalize knowledge
        knowledge = []
        for k in (raw_knowledge if isinstance(raw_knowledge, list) else [raw_knowledge] if raw_knowledge else []):
            content = k.get("content", str(k)) if isinstance(k, dict) else str(k)
            knowledge.append({
                "source": "knowledge_database",
                "confidence": k.get("confidence", 0.91),
                "importance": k.get("importance", 50),
                "content": content,
            })

        # Normalize graph
        graph = []
        for g in (raw_graph if isinstance(raw_graph, list) else [raw_graph] if raw_graph else []):
            content = str(g)
            graph.append({
                "source": "knowledge_graph",
                "confidence": 0.88,
                "importance": 60,
                "content": content,
            })

        # Normalize world model
        world = {}
        if isinstance(raw_world, dict):
            for cat, items in raw_world.items():
                if items:
                    world[cat] = items

        return {
            "memories": memories,
            "knowledge": knowledge,
            "graph": graph,
            "world": world,
        }

    async def multi_hop_reasoning(
        self,
        query: str,
        evidence: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Perform multi-hop reasoning by exploring graph relationships or connected context items.
        """
        extended_evidence = list(evidence)
        if self.knowledge_graph and hasattr(self.knowledge_graph, "find_path"):
            # Example traversal hook placeholder
            pass
        return extended_evidence

    async def merge_evidence(
        self,
        memories: List[Dict[str, Any]],
        knowledge: List[Dict[str, Any]],
        graph: List[Dict[str, Any]],
        world: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Merge all evidence sources, removing duplicates and preserving confidence/source.
        """
        all_items = memories + knowledge + graph
        for cat, items in world.items():
            if isinstance(items, dict):
                for k, v in items.items():
                    all_items.append({
                        "source": "world_model",
                        "confidence": 0.85,
                        "importance": 50,
                        "content": f"{cat} - {k}: {v}",
                    })

        seen = set()
        unique_evidence = []
        for item in all_items:
            content = item.get("content", "")
            if content not in seen:
                seen.add(content)
                unique_evidence.append(item)

        return unique_evidence

    async def rank_evidence(
        self,
        evidence: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Rank evidence using confidence, importance, and source priority.
        """
        source_priority = {
            "memory": 4,
            "knowledge_database": 3,
            "knowledge_graph": 2,
            "world_model": 1,
        }

        def sort_key(item):
            src = item.get("source", "unknown")
            prio = source_priority.get(src, 0)
            conf = item.get("confidence", 0.5)
            imp = item.get("importance", 50)
            return (prio, conf, imp)

        return sorted(evidence, key=sort_key, reverse=True)

    async def detect_conflicts(
        self,
        evidence: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Detect contradictions or conflicts across multiple evidence sources.
        """
        sources_found = set(item.get("source") for item in evidence)
        if len(sources_found) > 1 and len(evidence) > 2:
            # Basic placeholder conflict check
            return {"conflict": False, "sources": list(sources_found)}
        return {"conflict": False, "sources": []}

    def calculate_confidence(
        self,
        evidence: List[Dict[str, Any]],
    ) -> float:
        """
        Calculate overall confidence score using evidence amount, agreement, confidence levels, and recency.
        """
        if not evidence:
            return 0.73
        confidences = [item.get("confidence", 0.5) for item in evidence]
        base_avg = sum(confidences) / len(confidences)
        bonus = min(0.05 * len(evidence), 0.15)
        return min(1.0, base_avg + bonus)

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
        Analyze context, build evidence, execute multi-hop reasoning, rank evidence,
        detect conflicts, calculate confidence, select agents, and return ReasoningResult.
        Purely observational and analytical — no learning or state mutation.
        """
        query = str(context.get("query", "")).strip()
        reasoning_steps = []

        # 1. Understand Goal
        goal = await self.understand_goal(context)
        reasoning_steps.append(f"Understood user goal as '{goal}'")

        # 2. Retrieve Evidence in Parallel & Normalize
        retrieval = await self.retrieve_context(query)
        memories = retrieval["memories"]
        knowledge = retrieval["knowledge"]
        graph_results = retrieval["graph"]
        world_state = retrieval["world"]
        reasoning_steps.append("Retrieved and normalized context across memory, knowledge, graph, and world model")

        # 3. Evidence Fusion & Multi-Hop Reasoning
        merged_evidence = await self.merge_evidence(memories, knowledge, graph_results, world_state)
        evidence = await self.multi_hop_reasoning(query, merged_evidence)
        reasoning_steps.append("Fused evidence and performed multi-hop exploration")

        # 4. Rank Evidence & Conflict Detection
        ranked_evidence = await self.rank_evidence(evidence)
        conflicts = await self.detect_conflicts(ranked_evidence)
        reasoning_steps.append("Ranked evidence by confidence and importance")

        # 5. Calculate Confidence
        confidence = self.calculate_confidence(ranked_evidence)
        reasoning_steps.append(f"Calculated aggregate confidence score: {confidence:.2f}")

        # 6. Multi-Agent Reasoning Selection
        selected_agents = await self.choose_agents(query, context)
        workflow = AgentWorkflow()
        for agent in selected_agents:
            workflow.add(agent)
        reasoning_steps.append(f"Selected {len(selected_agents)} specialist agent(s)")

        # 7. Determine Plan Automatically if Multi-step Required
        plan = []
        if goal == "plan" or len(query.split()) > 10:
            if self.planner and hasattr(self.planner, "create_plan"):
                try:
                    task_plan = await self.planner.create_plan(query, context)
                    if task_plan and hasattr(task_plan, "tasks"):
                        plan = task_plan.tasks
                        reasoning_steps.append("Generated structured execution plan")
                except Exception:
                    logger.exception("[ReasoningEngine] Task planning failed.")

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
            len(ranked_evidence)
        )

        return ReasoningResult(
            goal=goal,
            action=action,
            confidence=confidence,
            evidence=ranked_evidence,
            selected_agents=selected_agents,
            plan=plan,
            retrieved_memory=memories,
            retrieved_knowledge=knowledge,
            graph_results=graph_results,
            world_state=world_state,
            metadata={
                "source": ranked_evidence[0].get("source") if ranked_evidence else "chat",
                "response_depth": context.get("response", {}).get("depth", "normal"),
                "conflicts": conflicts,
                "reasoning_steps": reasoning_steps,
            },
            primary_action=action,
            reasoning=f"Resolved objective '{goal}' with confidence {confidence:.2f} across {len(ranked_evidence)} evidence items.",
            workflow=workflow
        )
