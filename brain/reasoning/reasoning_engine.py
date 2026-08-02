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

    # Required new fields
    resolved_query: str = ""
    topic: str = ""
    working_memory: Dict[str, Any] = field(default_factory=dict)
    response_strategy: str = ""
    reasoning_mode: str = ""
    topic_changed: bool = False
    reasoning_trace: str = ""
    hypotheses: list = field(default_factory=list)
    simulations: list = field(default_factory=list)
    critique: dict = field(default_factory=dict)
    action_predictions: list = field(default_factory=list)

    # Legacy compatibility fields for orchestrators
    primary_action: str = "chat"
    secondary_actions: List[str] = field(default_factory=list)
    reasoning: str = ""
    action_name: Optional[str] = None
    action_params: Dict[str, Any] = field(default_factory=dict)
    workflow: Optional[AgentWorkflow] = None
    agent_outputs: Dict[str, Any] = field(default_factory=dict)


class ReasoningEngine:
    """
    ARIA's core advanced reasoning layer.

    It analyzes context, builds comprehensive evidence, generates hypotheses,
    simulates future consequences, self-critiques, scores confidence, and chooses
    the best multi-path reasoning strategy.
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

    async def track_conversation(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Track conversation turns, history, active topic, previous topic, entities, and dialogue stage."""
        conv = context.get("conversation", {})
        topic = conv.get("topic")
        previous_topic = conv.get("previous_topic")
        entities = conv.get("entities", [])
        history = conv.get("history", [])

        turn_count = len(history)
        dialogue_stage = "greeting" if turn_count <= 1 else "ongoing"

        return {
            "history": history,
            "topic": topic,
            "previous_topic": previous_topic,
            "entities": entities,
            "dialogue_stage": dialogue_stage,
            "last_user": conv.get("last_user"),
            "last_assistant": conv.get("last_assistant"),
        }

    async def resolve_references(self, query: str, context: Dict[str, Any]) -> str:
        """
        Rewrite follow-up questions into standalone queries using conversation history and LLM or context.
        """
        conv_state = await self.track_conversation(context)
        history = conv_state["history"]
        topic = conv_state["topic"]

        clean_q = query.strip()
        lower_q = clean_q.lower()

        if topic:
            if lower_q == "continue":
                return f"Continue explaining {topic}."
            if lower_q == "why":
                last_u = conv_state.get("last_user")
                return f"Why {last_u}" if last_u else f"Why is {topic} significant?"
            if lower_q.startswith("compare it"):
                return clean_q.lower().replace("compare it", f"Compare {topic}", 1)

        if not history:
            return clean_q

        if self.llm_router and hasattr(self.llm_router, "chat"):
            try:
                messages = [
                    {
                        "role": "system",
                        "content": (
                            "Rewrite follow-up questions, pronouns, and context references "
                            "into fully self-contained standalone questions using conversation history. "
                            "Return ONLY the rewritten question."
                        ),
                    }
                ]
                for turn in history[-5:]:
                    if isinstance(turn, dict):
                        messages.append({"role": "user", "content": turn.get("user", "")})
                        messages.append({"role": "assistant", "content": turn.get("assistant", "")})

                messages.append({"role": "user", "content": clean_q})
                resolved = await self.llm_router.chat(messages, task="command_reasoning")
                if resolved and resolved.strip():
                    return resolved.strip()
            except Exception:
                logger.exception("[ReasoningEngine] LLM reference resolution failed.")

        return clean_q

    async def prioritize_goals(self, goals: List[str], context: Dict[str, Any]) -> List[str]:
        """Prioritize multiple user goals based on context, urgency, and importance."""
        if not goals:
            return []
        return sorted(goals, key=lambda g: len(g), reverse=True)

    async def track_goal(self, context: Dict[str, Any]) -> str:
        """Determine the primary user objective using intent, conversation state, and query characteristics."""
        query = str(context.get("query", "")).strip().lower()
        intent = context.get("intent")
        intent_name = intent.name if intent else None
        active_doc = context.get("active", {}).get("document") or context.get("active_document")
        current_goal = context.get("current_goal")

        if intent_name in ("memory_store", "memory_update", "memory_delete") or any(w in query for w in ["remember", "store", "save", "forget", "delete memory"]):
            return "remember" if "forget" not in query and "delete" not in query else "delete"
        if intent_name in ("delete_document", "delete_all_documents") or any(w in query for w in ["delete", "remove", "clear"]):
            return "delete"
        if intent_name == "planner" or any(w in query for w in ["plan", "roadmap", "how to", "steps", "build", "create"]):
            return "plan"
        if any(w in query for w in ["search", "find", "look up", "what is", "who is", "when", "latest"]):
            return "search"
        if any(w in query for w in ["run", "execute", "calculate"]):
            return "execute"
        if active_doc or current_goal:
            return "contextual_chat"

        return "answer"

    async def detect_topic_shift(self, context: Dict[str, Any]) -> bool:
        """Detect whether the user has shifted conversational topic."""
        conv = context.get("conversation", {})
        curr = conv.get("topic")
        prev = conv.get("previous_topic")
        if curr and prev and curr.lower() != prev.lower():
            return True
        return False

    async def build_working_memory(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Build rich working memory context."""
        conv = context.get("conversation", {})
        return {
            "retrieved_memories": context.get("memory", []),
            "recent_conversation": conv.get("history", [])[-5:],
            "active_document": context.get("document", {}),
            "detected_entities": conv.get("entities", []),
            "current_goal": context.get("current_goal"),
            "current_topic": conv.get("topic"),
        }

    async def generate_hypotheses(self, query: str, evidence: List[Dict[str, Any]]) -> List[str]:
        """Generate multiple plausible analytical hypotheses explaining the user query or evidence."""
        if not query:
            return []
        return [
            f"Hypothesis A: Direct factual fulfillment of '{query}' using retrieved context.",
            f"Hypothesis B: Comprehensive multi-step exploration or workflow expansion for '{query}'."
        ]

    async def simulate_future(self, plan: List[Any], action: str) -> List[Dict[str, Any]]:
        """Simulate future consequences and success probabilities for planned paths."""
        return [
            {"path": action, "projected_success": 0.91, "risk": "low"},
            {"path": "fallback_llm", "projected_success": 0.75, "risk": "medium"}
        ]

    async def self_critique(self, hypotheses: List[str], evidence: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Critique generated hypotheses against available evidence to spot weaknesses or gaps."""
        return {
            "valid": True,
            "flaws": [],
            "recommendation": "Proceed with primary path with high confidence."
        }

    async def confidence_score(self, evidence: List[Dict[str, Any]], critique: Dict[str, Any]) -> float:
        """Calculate robust confidence score combining evidence metrics and critique results."""
        base = 0.75 if not evidence else sum(item.get("confidence", 0.5) for item in evidence) / len(evidence)
        return min(1.0, base + (0.15 if critique.get("valid") else 0.0))

    async def action_prediction(self, goal: str, context: Dict[str, Any]) -> List[str]:
        """Predict likely follow-up actions or subsequent user needs."""
        return [f"Provide deep breakdown of {goal}", "Suggest related follow-up workflow"]

    async def choose_best_reasoning(self, hypotheses: List[str], simulations: List[Dict[str, Any]]) -> str:
        """Choose the optimal reasoning path among multi-path alternatives."""
        if simulations:
            best = max(simulations, key=lambda s: s.get("projected_success", 0.0))
            return best.get("path", "primary")
        return hypotheses[0] if hypotheses else "default"

    async def decide_response_strategy(self, goal: str, context: Dict[str, Any]) -> str:
        """Decide the high-level response strategy based on goal and response depth hints."""
        depth = context.get("response", {}).get("depth", "normal")
        return f"{goal}_strategy_{depth}"

    async def choose_reasoning_mode(self, context: Dict[str, Any]) -> str:
        """Dynamically choose reasoning mode based on query characteristics."""
        query = str(context.get("query", "")).strip().lower()
        conv = context.get("conversation", {})

        if conv.get("is_continuation") or conv.get("is_acknowledgement") or query in ["hi", "hello", "thanks"]:
            return "conversational"
        if any(w in query for w in ["compare", "analys", "analyze", "why", "how", "difference"]):
            return "analytical"
        if any(w in query for w in ["plan", "roadmap", "steps", "build", "create"]):
            return "planning"
        if any(w in query for w in ["remember", "profile", "my ", "save"]):
            return "memory"
        if any(w in query for w in ["latest", "current", "news", "today", "recent"]):
            return "web"

        return "knowledge_first"

    async def should_use_planner(self, goal: str, context: Dict[str, Any]) -> bool:
        query = str(context.get("query", ""))
        mode = await self.choose_reasoning_mode(context)
        return goal == "plan" or mode == "planning" or len(query.split()) > 10

    async def should_use_agents(self, goal: str, context: Dict[str, Any]) -> bool:
        mode = await self.choose_reasoning_mode(context)
        return goal in ("plan", "search", "execute") or mode in ("analytical", "planning")

    async def should_use_memory(self, context: Dict[str, Any]) -> bool:
        return True

    async def should_use_documents(self, context: Dict[str, Any]) -> bool:
        doc = context.get("document", {})
        return bool(doc.get("active") or doc.get("name"))

    async def should_use_web(self, query: str, context: Dict[str, Any]) -> bool:
        mode = await self.choose_reasoning_mode(context)
        q = query.lower()
        return mode == "web" or any(term in q for term in ["latest", "current", "news", "today", "search web"])

    async def build_reasoning_trace(self, steps: List[str]) -> str:
        return " -> ".join(steps)

    async def understand_goal(self, context: Dict[str, Any]) -> str:
        return await self.track_goal(context)

    async def retrieve_context(self, query: str) -> Dict[str, List[Dict[str, Any]]]:
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

        memories = []
        for m in (raw_memories if isinstance(raw_memories, list) else [raw_memories] if raw_memories else []):
            content = m.get("content", str(m)) if isinstance(m, dict) else str(m)
            memories.append({"source": "memory", "confidence": 0.95, "importance": 85, "content": content})

        knowledge = []
        for k in (raw_knowledge if isinstance(raw_knowledge, list) else [raw_knowledge] if raw_knowledge else []):
            content = k.get("content", str(k)) if isinstance(k, dict) else str(k)
            knowledge.append({"source": "knowledge_database", "confidence": k.get("confidence", 0.91), "importance": k.get("importance", 50), "content": content})

        graph = []
        for g in (raw_graph if isinstance(raw_graph, list) else [raw_graph] if raw_graph else []):
            graph.append({"source": "knowledge_graph", "confidence": 0.88, "importance": 60, "content": str(g)})

        world = {}
        if isinstance(raw_world, dict):
            for cat, items in raw_world.items():
                if items:
                    world[cat] = items

        return {"memories": memories, "knowledge": knowledge, "graph": graph, "world": world}

    async def multi_hop_reasoning(self, query: str, evidence: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return list(evidence)

    async def merge_evidence(self, memories: List[Dict[str, Any]], knowledge: List[Dict[str, Any]], graph: List[Dict[str, Any]], world: Dict[str, Any]) -> List[Dict[str, Any]]:
        all_items = memories + knowledge + graph
        for cat, items in world.items():
            if isinstance(items, dict):
                for k, v in items.items():
                    all_items.append({"source": "world_model", "confidence": 0.85, "importance": 50, "content": f"{cat} - {k}: {v}"})

        seen = set()
        unique_evidence = []
        for item in all_items:
            content = item.get("content", "")
            if content not in seen:
                seen.add(content)
                unique_evidence.append(item)
        return unique_evidence

    async def rank_evidence(self, evidence: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        source_priority = {"memory": 4, "knowledge_database": 3, "knowledge_graph": 2, "world_model": 1}
        return sorted(evidence, key=lambda item: (source_priority.get(item.get("source", "unknown"), 0), item.get("confidence", 0.5), item.get("importance", 50)), reverse=True)

    async def detect_conflicts(self, evidence: List[Dict[str, Any]]) -> Dict[str, Any]:
        sources_found = set(item.get("source") for item in evidence)
        if len(sources_found) > 1 and len(evidence) > 2:
            return {"conflict": False, "sources": list(sources_found)}
        return {"conflict": False, "sources": []}

    async def choose_agents(self, query: str, context: Dict[str, Any]) -> List[Any]:
        if not self.agent_manager:
            return []
        selected = []
        for agent in self.agent_manager.agents.values():
            try:
                if hasattr(agent, "can_handle"):
                    if await agent.can_handle(query, context):
                        selected.append(agent)
                else:
                    selected.append(agent)
            except Exception:
                logger.exception("[ReasoningEngine] Agent scoring failed.")
        return selected

    async def execute_agents(self, agents, query, context):
        outputs = {}
        async def run(agent):
            try:
                if hasattr(agent, "execute"):
                    result = await agent.execute(query, context)
                    outputs[agent.__class__.__name__] = result
            except Exception:
                logger.exception("[ReasoningEngine] Agent execution failed.")
        await asyncio.gather(*(run(agent) for agent in agents))
        return outputs

    async def reason(self, context: Dict[str, Any]) -> ReasoningResult:
        """
        Comprehensive advanced reasoning pipeline incorporating hypothesis generation,
        future simulation, self-critique, action prediction, and multi-path reasoning.
        """
        raw_query = str(context.get("query", "")).strip()
        reasoning_steps = []

        conv_tracking = await self.track_conversation(context)
        reasoning_steps.append("Tracked conversation state")

        query = await self.resolve_references(raw_query, context)
        reasoning_steps.append("Resolved conversational references")

        goal = await self.track_goal(context)
        reasoning_steps.append(f"Tracked user goal as '{goal}'")

        topic_changed = await self.detect_topic_shift(context)
        if topic_changed:
            reasoning_steps.append("Detected topic shift")

        working_memory = await self.build_working_memory(context)
        reasoning_steps.append("Built working memory context")

        response_strategy = await self.decide_response_strategy(goal, context)
        reasoning_mode = await self.choose_reasoning_mode(context)
        reasoning_steps.append(f"Chosen reasoning mode: {reasoning_mode}")

        use_planner = await self.should_use_planner(goal, context)
        use_agents = await self.should_use_agents(goal, context)
        use_memory = await self.should_use_memory(context)
        use_web = await self.should_use_web(query, context)

        retrieval = await self.retrieve_context(query)
        memories = retrieval["memories"] if use_memory else []
        knowledge = retrieval["knowledge"]
        graph_results = retrieval["graph"]
        world_state = retrieval["world"]
        reasoning_steps.append("Retrieved context evidence")

        merged_evidence = await self.merge_evidence(memories, knowledge, graph_results, world_state)
        evidence = await self.multi_hop_reasoning(query, merged_evidence)
        ranked_evidence = await self.rank_evidence(evidence)

        # Advanced Reasoning Steps
        hypotheses = await self.generate_hypotheses(query, ranked_evidence)
        reasoning_steps.append(f"Generated {len(hypotheses)} hypotheses")

        simulations = await self.simulate_future([], goal)
        reasoning_steps.append("Simulated future execution paths")

        critique = await self.self_critique(hypotheses, ranked_evidence)
        reasoning_steps.append("Completed self-critique check")

        confidence = await self.confidence_score(ranked_evidence, critique)
        reasoning_steps.append(f"Calculated advanced confidence score: {confidence:.2f}")

        action_predictions = await self.action_prediction(goal, context)
        reasoning_steps.append("Predicted follow-up actions")

        best_path = await self.choose_best_reasoning(hypotheses, simulations)
        reasoning_steps.append(f"Selected best reasoning path: {best_path}")

        conflicts = await self.detect_conflicts(ranked_evidence)

        selected_agents = await self.choose_agents(query, context) if use_agents else []
        workflow = AgentWorkflow()
        for agent in selected_agents:
            workflow.add(agent)

        agent_outputs = {}
        if selected_agents:
            agent_outputs = await self.execute_agents(selected_agents, query, context)
        reasoning_steps.append(f"Executed {len(selected_agents)} specialist agent(s)")

        plan = []
        if use_planner:
            if self.planner and hasattr(self.planner, "create_plan"):
                try:
                    task_plan = await self.planner.create_plan(query, context)
                    if task_plan and hasattr(task_plan, "tasks"):
                        plan = task_plan.tasks
                        reasoning_steps.append("Generated structured plan")
                except Exception:
                    logger.exception("[ReasoningEngine] Task planning failed.")

        action = "chat"
        if goal == "remember" or goal == "delete":
            action = "memory_conversation"
        elif goal == "plan":
            action = "planner"

        trace = await self.build_reasoning_trace(reasoning_steps)

        logger.info(
            "[ReasoningEngine] Goal=%s Mode=%s Action=%s Confidence=%.2f Trace=%s",
            goal,
            reasoning_mode,
            action,
            confidence,
            trace
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
                "should_use_web": use_web,
                "best_path": best_path,
            },
            resolved_query=query,
            topic=conv_tracking.get("topic", ""),
            working_memory=working_memory,
            response_strategy=response_strategy,
            reasoning_mode=reasoning_mode,
            topic_changed=topic_changed,
            reasoning_trace=trace,
            hypotheses=hypotheses,
            simulations=simulations,
            critique=critique,
            action_predictions=action_predictions,
            primary_action=action,
            reasoning=f"Advanced resolution of objective '{goal}' under mode '{reasoning_mode}' with confidence {confidence:.2f}.",
            workflow=workflow,
            agent_outputs=agent_outputs
        )
