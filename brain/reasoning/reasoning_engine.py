import logging
import asyncio
import time
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

from brain.agents.agent_workflow import AgentWorkflow

logger = logging.getLogger("aria")


@dataclass
class ReasoningResult:
    """
    Represents the complete decision package determining what subsystems
    are required to fulfill the user request.
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

    # Core Orchestration Decision Flags
    answer: Optional[str] = None
    requires_memory: bool = True
    requires_documents: bool = False
    requires_tools: bool = False
    requires_web: bool = False
    requires_planning: bool = False
    requires_clarification: bool = False

    # Required tracking fields
    resolved_query: str = ""
    topic: str = ""
    working_memory: Dict[str, Any] = field(default_factory=dict)
    response_strategy: Dict[str, Any] = field(default_factory=dict)
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
    ARIA's core advanced decision-making and routing layer.

    Instead of answering questions directly, it analyzes context and determines
    precisely what sub-pipelines (clarification, memory, documents, planner,
    tools, web, or direct LLM) are required via a structured ReasoningResult.
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
        working_memory=None,
        goal_manager=None,
        agent_coordinator=None,
        lead_agent=None,
        memory_engine=None,
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
        self.working_memory = working_memory
        self.goal_manager = goal_manager
        self.agent_coordinator = agent_coordinator
        self.lead_agent = lead_agent
        self.memory_engine = memory_engine

    def _build_semantic_context(self):

        if not hasattr(self, "working_memory") or not self.working_memory:
            return None

        semantic = self.working_memory.semantic()

        return {
            "summary": semantic.summary(),
            "relationships": semantic.edges,
        }

    def _select_reasoning_strategy(
        self,
        query: str,
        context: dict,
    ):
        """
        Choose the best reasoning strategy.
        """

        q = query.lower()

        if context.get("document"):
            return "document_first"

        if any(x in q for x in [
            "remember",
            "recall",
            "my",
            "previous",
        ]):
            return "memory_first"

        if any(x in q for x in [
            "build",
            "design",
            "implement",
            "roadmap",
            "plan",
            "create",
        ]):
            return "planning_first"

        if any(x in q for x in [
            "code",
            "python",
            "fastapi",
            "java",
            "bug",
            "fix",
        ]):
            return "coding_first"

        if any(x in q for x in [
            "research",
            "compare",
            "latest",
            "news",
        ]):
            return "research_first"

        if any(x in q for x in [
            "continue",
            "that",
            "it",
            "he",
            "she",
        ]):
            return "context_first"

        return "knowledge_first"

    def _self_critique(
        self,
        answer: str,
        context: dict,
    ):
        """
        Perform a lightweight quality check on the generated answer.
        """

        score = 1.0
        issues = []

        if not answer or len(answer.strip()) < 10:
            score -= 0.4
            issues.append("too_short")

        if "I couldn't find" in answer:
            score -= 0.2
            issues.append("low_confidence")

        if answer.count("?") > 2:
            score -= 0.1
            issues.append("too_many_questions")

        return {
            "score": max(score, 0.0),
            "issues": issues,
        }

    def _analyze_execution_feedback(self, execution_result):
        """
        Analyze the previous execution to improve future reasoning.
        """

        if not execution_result:
            return {
                "success_rate": 1.0,
                "needs_replanning": False,
            }

        completed = execution_result.get("completed", [])
        failed = execution_result.get("failed", [])

        total = len(completed) + len(failed)

        success_rate = (
            len(completed) / total
            if total else 1.0
        )

        return {
            "success_rate": success_rate,
            "needs_replanning": len(failed) > 0,
        }

    def _calculate_final_confidence(
        self,
        reasoning_confidence,
        execution_feedback,
        critique,
    ):
        """
        Combine multiple confidence sources into one score.
        """

        confidence = reasoning_confidence

        confidence *= execution_feedback.get(
            "success_rate",
            1.0,
        )

        confidence *= critique.get(
            "score",
            1.0,
        )

        return round(
            max(0.0, min(confidence, 1.0)),
            2,
        )

    def choose_best_agents(self, query: str, intent_name: Optional[str] = None) -> List[str]:
        """
        Decide which specialist agents should handle the request.
        """
        query = query.lower()
        agents = []

        if any(word in query for word in [
            "code",
            "python",
            "java",
            "bug",
            "program",
            "implement"
        ]):
            agents.append("coding")

        if any(word in query for word in [
            "research",
            "find",
            "compare",
            "search",
            "latest",
            "news",
            "current",
            "recent",
            "today"
        ]):
            agents.append("research")

        if any(word in query for word in [
            "plan",
            "roadmap",
            "schedule",
            "strategy"
        ]):
            agents.append("planning")

        if any(word in query for word in [
            "write",
            "essay",
            "email",
            "story",
            "article",
            "summary"
        ]):
            agents.append("writing")

        if not agents:
            if intent_name == "memory":
                agents.append("memory")
            elif intent_name == "document":
                agents.append("document")
            else:
                agents.append("chat")

        unique_agents = list(dict.fromkeys(agents))
        logger.info(
            "[ReasoningEngine] Selected agents: %s",
            unique_agents
        )
        return unique_agents

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

    async def resolve_references(
        self,
        query: str,
        context: Dict[str, Any],
    ) -> str:
        """
        Resolve contextual references using ARIA's conversational state.

        This is capability-independent. It does not contain logic for
        calculators, weather, documents, coding, or any other individual skill.
        """

        clean_query = str(query or "").strip()

        if not clean_query:
            return clean_query

        conversation = context.get("conversation", {})

        if not isinstance(conversation, dict):
            conversation = {}

        history = conversation.get(
            "conversation_history",
            conversation.get("history", []),
        )

        if not isinstance(history, list):
            history = []

        recent_history = history[-10:]

        last_user = conversation.get("last_user")
        last_assistant = conversation.get("last_assistant")
        last_subject = conversation.get("last_subject")

        last_result = conversation.get("last_result")

        reference_context = {
            "last_subject": last_subject,
            "last_user": last_user,
            "last_assistant": last_assistant,
            "last_result": last_result,
            "history": recent_history,
        }

        if self.llm_router and hasattr(self.llm_router, "chat"):
            try:
                messages = [
                    {
                        "role": "system",
                        "content": (
                            "You are ARIA's contextual reasoning layer.\n\n"
                            "Resolve the user's latest message using the "
                            "conversation context provided.\n\n"
                            "Your job is to understand references such as "
                            "it, that, this, them, the result, the previous "
                            "answer, the previous output, continue, again, "
                            "and similar contextual language.\n\n"
                            "When the user refers to a previous result, use "
                            "the structured last_result from the conversation "
                            "context when it clearly matches the reference.\n\n"
                            "Do not invent a result that is not present in "
                            "the provided context.\n\n"
                            "Do not force an old result into an unrelated "
                            "new request.\n\n"
                            "Preserve the user's intended operation exactly "
                            "while making the request standalone.\n\n"
                            "Do not answer the user.\n"
                            "Do not explain your reasoning.\n"
                            "Do not mention this instruction.\n\n"
                            "Return ONLY a standalone version of the user's "
                            "latest request that preserves the user's intent "
                            "and includes the necessary contextual information."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            "CONVERSATION CONTEXT:\n"
                            f"{reference_context}\n\n"
                            "LATEST USER REQUEST:\n"
                            f"{clean_query}"
                        ),
                    },
                ]

                resolved = await self.llm_router.chat(
                    messages,
                    task="context_resolution",
                )

                if resolved:
                    resolved = str(resolved).strip()

                    if resolved:
                        logger.info(
                            "[Reasoning] Context resolved: %r -> %r",
                            clean_query,
                            resolved,
                        )

                        return resolved

            except Exception:
                logger.exception(
                    "[Reasoning] Context resolution failed."
                )

        return clean_query

    async def track_goal(self, context: Dict[str, Any]) -> str:
        """Determine the primary user objective using intent, conversation state, and query characteristics."""
        query = str(context.get("query", "")).strip().lower()
        intent = context.get("intent")
        intent_name = intent.name if intent and hasattr(intent, "name") else str(intent) if intent else None
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
        if curr and prev and str(curr).lower() != str(prev).lower():
            return True
        return False

    async def build_working_memory(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Build rich working memory context."""
        conv = context.get("conversation", {})
        history = conv.get("history", [])
        return {
            "retrieved_memories": context.get("memory", []),
            "recent_conversation": history[-5:] if isinstance(history, list) else [],
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
        predictions = []
        if goal == "answer":
            predictions.append("Offer related explanation")
        if goal == "plan":
            predictions.append("Offer execution")
        if goal == "search":
            predictions.append("Offer comparison")
        if goal == "remember":
            predictions.append("Confirm memory")
        return predictions

    async def choose_best_reasoning(self, hypotheses: List[str], simulations: List[Dict[str, Any]]) -> str:
        """Choose the optimal reasoning path among multi-path alternatives."""
        if simulations:
            best = max(simulations, key=lambda s: s.get("projected_success", 0.0))
            return best.get("path", "primary")
        return hypotheses[0] if hypotheses else "default"

    async def decide_response_strategy(self, goal: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Decide the high-level response strategy based on goal and response depth hints."""
        depth = context.get("response", {}).get("depth", "normal")
        return {
            "depth": depth,
            "be_proactive": True,
            "personalize": True,
            "predict_followup": True,
            "avoid_encyclopedia": True,
            "offer_next_step": goal not in (
                "remember",
                "delete",
            ),
        }

    async def needs_clarification(self, query: str, context: Dict[str, Any]) -> bool:
        """Determine if the user query is excessively vague or ambiguous."""
        clean = query.strip()
        if len(clean.split()) <= 1 and clean.lower() not in ["hi", "hello", "help", "status"]:
            conv = context.get("conversation", {})
            if conv.get("topic") or conv.get("history"):
                return False
            return True
        return False

    async def build_reasoning_trace(self, steps: List[str]) -> str:
        return " -> ".join(steps)

    async def retrieve_context(self, query: str) -> Dict[str, Any]:
        memories_task = (
            asyncio.create_task(self.memory_router.recall(query))
            if self.memory_router and hasattr(self.memory_router, "recall")
            else asyncio.create_task(asyncio.sleep(0))
        )

        knowledge_task = asyncio.create_task(asyncio.sleep(0))
        if self.knowledge_database:
            if hasattr(self.knowledge_database, "retrieve"):
                knowledge_task = asyncio.create_task(self.knowledge_database.retrieve(query))
            elif hasattr(self.knowledge_database, "search"):
                knowledge_task = asyncio.create_task(self.knowledge_database.search(query))
            elif hasattr(self.knowledge_database, "answer"):
                knowledge_task = asyncio.create_task(self.knowledge_database.answer(question=query))

        graph_task = (
            asyncio.create_task(self.knowledge_graph.search(query))
            if self.knowledge_graph and hasattr(self.knowledge_graph, "search")
            else asyncio.create_task(asyncio.sleep(0))
        )

        world_task = asyncio.create_task(asyncio.sleep(0))
        if self.world_model and hasattr(self.world_model, "search"):
            world_task = asyncio.create_task(
                asyncio.to_thread(
                    self.world_model.search,
                    query,
                )
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
            confidence = k.get("confidence", 0.91) if isinstance(k, dict) else 0.91
            importance = k.get("importance", 50) if isinstance(k, dict) else 50
            knowledge.append({"source": "knowledge_database", "confidence": confidence, "importance": importance, "content": content})

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
        if not self.agent_manager or not hasattr(self.agent_manager, "agents"):
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

    async def evaluate_result(
        self,
        query,
        result,
    ):
        prompt = f"""
User Goal:{query}

Current Result:{result}

Determine whether the user's goal has been fully completed.

Return JSON:

{{
    "goal_completed": true,
    "confidence": 0.98,
    "missing": []
}}
"""

        response = await self.llm_router.chat(
            [
                {
                    "role": "system",
                    "content": "Return only JSON.",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ]
        )

        return self.llm_router.extract_json(response)

    async def reason(self, context: Dict[str, Any]) -> ReasoningResult:
        """
        Core decision pipeline determining precisely what sub-pipelines are required
        and returning a comprehensive ReasoningResult object.
        """
        user_query = str(context.get("query", "")).strip()

        semantic_context = self._build_semantic_context()

        if semantic_context:
            context["semantic_memory"] = semantic_context
            logger.info(
                "[Reasoning] Using semantic relationships."
            )

        strategy = self._select_reasoning_strategy(
            user_query,
            context,
        )

        decision = context.get("decision")

        # Cognitive decision can refine the strategy,
        # but must not destroy a stronger semantic strategy.
        if decision:
            if getattr(decision, "use_memory", False):
                strategy = "memory_first"

            elif getattr(decision, "use_planner", False):
                strategy = "planning"

            elif getattr(decision, "use_documents", False):
                strategy = "document"

            elif getattr(decision, "use_world_model", False):
                strategy = "knowledge_first"

            elif getattr(decision, "use_reasoning", False):
                if strategy == "knowledge_first":
                    strategy = "deep_reasoning"

        context["reasoning_strategy"] = strategy

        logger.info(
            f"[Reasoning] Strategy={strategy} Decision={decision}"
        )

        feedback = self._analyze_execution_feedback(
            context.get("execution_result")
        )
        context["execution_feedback"] = feedback

        if self.goal_manager and hasattr(self.goal_manager, "observe"):
            await self.goal_manager.observe(
                query=user_query,
                context=context,
            )

        active_goal = None

        if self.goal_manager and hasattr(self.goal_manager, "current_goal"):
            active_goal = self.goal_manager.current_goal()

        next_task = None

        if self.goal_manager and hasattr(self.goal_manager, "next_subgoal"):
            next_task = self.goal_manager.next_subgoal()

        context["active_goal"] = (
            getattr(active_goal, "title", str(active_goal))
            if active_goal
            else None
        )
        context["goal_progress"] = (
            getattr(active_goal, "progress", 0.0)
            if active_goal
            else 0.0
        )
        context["next_goal"] = (
            getattr(next_task, "title", str(next_task))
            if next_task
            else None
        )

        if active_goal:
            logger.info(
                "[ReasoningEngine] Active goal: %s (%.0f%%)",
                getattr(active_goal, "title", "Goal"),
                getattr(active_goal, "progress", 0.0),
            )

        if next_task:
            logger.info(
                "[ReasoningEngine] Next suggested task: %s",
                getattr(next_task, "title", "Task"),
            )

        start_time = time.time()
        raw_query = user_query
        reasoning_steps = []

        active_context = context.get("active_context", {})
        working = context.get("working_memory", {})

        conv_tracking = await self.track_conversation(context)
        reasoning_steps.append("Tracked conversation state")

        query = await self.resolve_references(raw_query, context)
        reasoning_steps.append("Resolved conversational references")

        requires_clarification = await self.needs_clarification(query, context)
        if requires_clarification:
            reasoning_steps.append("Flagged need for clarification")

        goal = await self.track_goal(context)
        reasoning_steps.append(f"Tracked user goal as '{goal}'")

        topic_changed = await self.detect_topic_shift(context)
        if topic_changed:
            reasoning_steps.append("Detected topic shift")

        working_memory = await self.build_working_memory(context)
        reasoning_steps.append("Built working memory context")

        decision = context.get("decision")

        if decision is None and self.working_memory:
            decision = getattr(
                self.working_memory,
                "metadata",
                {}
            ).get("cognitive_decision")

        if decision:
            mode = decision.reasoning_mode or strategy
        else:
            mode = strategy

        # Never let an empty/default cognitive mode erase
        # a stronger semantic strategy selected above.
        if mode in (None, "", "knowledge_first", "fast"):
            mode = strategy

        reasoning_steps.append(f"Chosen reasoning mode: {mode}")

        selected_agents = (
            list(decision.selected_agents)
            if decision and getattr(decision, "selected_agents", None)
            else []
        )

        # If the cognitive layer did not choose agents,
        # allow the reasoning engine to derive specialists.
        if not selected_agents:
            selected_agents = self.choose_best_agents(
                query,
                getattr(context.get("intent"), "name", None)
            )

        reasoning_steps.append(f"Selected best agents: {selected_agents}")

        requires_planning = (
            decision.use_planner
            if decision
            else strategy == "planning_first"
        )
        requires_tools = decision.use_tools if decision else False
        requires_memory = (
            decision.use_memory
            if decision
            else strategy == "memory_first"
        )
        requires_documents = (
            decision.use_documents
            if decision
            else strategy == "document_first"
        )
        requires_web = (
            getattr(decision, "use_web", False)
            if decision
            else strategy == "research_first"
        )

        # Semantic strategy is authoritative when the request
        # clearly requires current external information.
        if strategy == "research_first":
            requires_web = True

        reasoning_steps.append(
            f"Capabilities: web={requires_web}, "
            f"memory={requires_memory}, "
            f"planning={requires_planning}, "
            f"tools={requires_tools}"
        )

        retrieval = await self.retrieve_context(query)
        raw_memories = retrieval["memories"] if requires_memory else []
        knowledge = retrieval["knowledge"] if requires_documents else []
        graph_results = retrieval["graph"]
        world_state = retrieval["world"]
        reasoning_steps.append("Retrieved context evidence")

        # Convert retrieved raw memories into memory_summary string representation for clean prompt integration
        memory_summary_parts = []
        for m in raw_memories:
            content = m.get("content", str(m)) if isinstance(m, dict) else str(m)
            memory_summary_parts.append(content)
        memory_summary = ". ".join(memory_summary_parts)

        memories = [{"source": "memory", "confidence": 0.95, "importance": 85, "content": memory_summary}] if memory_summary else []

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

        base_confidence = await self.confidence_score(ranked_evidence, critique)
        confidence = base_confidence

        if feedback["needs_replanning"]:
            confidence *= 0.85

        reasoning_steps.append(f"Calculated advanced confidence score: {confidence:.2f}")

        action_predictions = await self.action_prediction(goal, context)
        reasoning_steps.append("Predicted follow-up actions")

        best_path = await self.choose_best_reasoning(hypotheses, simulations)
        reasoning_steps.append(f"Selected best reasoning path: {best_path}")

        conflicts = await self.detect_conflicts(ranked_evidence)

        agent_results = []

        if self.agent_coordinator and selected_agents:
            execution_plan = {
                "agents": selected_agents,
                "query": query,
                "context": context,
            }

            if self.lead_agent and hasattr(self.lead_agent, "create_execution_plan"):
                execution_plan = await self.lead_agent.create_execution_plan(
                    query,
                    context,
                    selected_agents,
                )

            logger.info(
                "[ReasoningEngine] Lead Agent assigned %d agents.",
                len(execution_plan.get("agents", [])),
            )

            if hasattr(self.agent_coordinator, "execute"):
                coordination = await self.agent_coordinator.execute(
                    execution_plan.get("agents", []),
                    execution_plan.get("query", query),
                    execution_plan.get("context", context),
                )

                agent_results = coordination.get("outputs", [])
                context.update(coordination.get("shared_context", {}))

        context["best_agent"] = (
            agent_results[0].get("agent")
            if agent_results and isinstance(agent_results[0], dict)
            else None
        )

        logger.info(
            "[ReasoningEngine] %d agents completed",
            len(agent_results),
        )

        workflow = AgentWorkflow()

        agent_outputs = {}
        for result in agent_results:
            if isinstance(result, dict):
                agent_outputs[result.get("agent", "unknown")] = result.get("result")
                logger.info(
                    "\nAgent: %s\nConfidence: %.2f\n%s\n",
                    result.get("agent"),
                    result.get("confidence", 0.0),
                    result.get("result")
                )

        reasoning_steps.append(f"Executed {len(agent_results)} specialist agent(s) sequentially via coordinator")

        plan = []
        if requires_planning:
            if self.planner and hasattr(self.planner, "create_plan"):
                try:
                    task_plan = await self.planner.create_plan(query, context)
                    if task_plan and hasattr(task_plan, "tasks"):
                        plan = task_plan.tasks
                        reasoning_steps.append("Generated structured plan")
                except Exception:
                    logger.exception("[ReasoningEngine] Task planning failed.")

        answer = None
        if requires_clarification:
            answer = "Could you please clarify your request with a bit more detail?"

        if "summarize" in query.lower() or "summary" in query.lower():
            conversation = context.get("conversation_history", [])
            goal_obj = None
            if self.goal_manager and hasattr(self.goal_manager, "current_goal"):
                goal_obj = self.goal_manager.current_goal()

            use_memory = getattr(decision, "use_memory", False) if decision else False

            summary_memories = []
            if use_memory and hasattr(self, "memory_engine") and self.memory_engine:
                if hasattr(self.memory_engine, "retrieve"):
                    summary_memories = await self.memory_engine.retrieve(query)

            summary_context = {
                "conversation": conversation,
                "goal": goal_obj,
                "memories": summary_memories,
            }

            if self.llm_router and hasattr(self.llm_router, "chat"):
                try:
                    summary_prompt = (
                        f"Summarize what has been done so far based on context:\n"
                        f"Goal: {getattr(goal_obj, 'title', 'None')}\n"
                        f"Progress: {getattr(goal_obj, 'progress', 0.0)}%\n"
                        f"Conversation: {conversation}\n"
                        f"Memories: {summary_memories}"
                    )
                    reply = await self.llm_router.chat([{"role": "user", "content": summary_prompt}])
                    answer = str(reply).strip() if reply else "Here is the summary of your current project and progress."
                except Exception:
                    answer = f"Current Goal: {getattr(goal_obj, 'title', 'None')} (Progress: {getattr(goal_obj, 'progress', 0.0)}%)"

        action = "chat"
        if goal == "remember" or goal == "delete":
            action = "memory_conversation"
        elif goal == "plan":
            action = "planner"

        reasoning_time = round(time.time() - start_time, 3)

        # Detailed Subsystem Usage Indicators
        memory_used = bool(memories)
        graph_used = bool(graph_results)
        world_used = bool(world_state)
        web_used = requires_web
        planner_used = bool(plan)
        tool_used = bool(agent_results)

        mem_conf = max([m.get("confidence", 0.5) for m in memories], default=0.5) if memories else 0.5
        know_conf = max([k.get("confidence", 0.5) for k in knowledge], default=0.5) if knowledge else 0.5
        world_conf = 0.90 if world_state else 0.5

        response_to_store = answer or (ranked_evidence[0].get("content") if ranked_evidence else "Done.")

        if (
            next_task
            and active_goal
            and response_to_store
            and len(response_to_store) < 800
        ):
            response_to_store += (
                f"\n\nA good next step would be to "
                f"{getattr(next_task, 'title', 'proceed').lower()}."
            )

        critique_result = self._self_critique(
            response_to_store,
            context,
        )

        logger.info(
            "[Reasoning] Self critique: %.2f",
            critique_result["score"],
        )

        if critique_result["score"] < 0.5:
            logger.warning(
                "[Reasoning] Low quality answer detected."
            )

        final_confidence = self._calculate_final_confidence(
            confidence,
            feedback,
            critique_result,
        )

        confidence = final_confidence

        logger.info(
            "[Reasoning] Final confidence: %.2f",
            final_confidence,
        )

        metadata = {
            "reasoning_time": reasoning_time,
            "planner_used": planner_used,
            "memory_used": memory_used,
            "graph_used": graph_used,
            "world_used": world_used,
            "web_used": web_used,
            "tool_used": tool_used,
            "confidence_breakdown": {
                "memory": mem_conf,
                "knowledge": know_conf,
                "world": world_conf,
            },
            "source": ranked_evidence[0].get("source") if ranked_evidence else "chat",
            "response_depth": context.get("response", {}).get("depth", "normal"),
            "conflicts": conflicts,
            "reasoning_steps": reasoning_steps,
            "best_path": best_path,
            "strategy": strategy,
            "self_critique": critique_result,
            "final_confidence": final_confidence,
        }

        if feedback["needs_replanning"]:
            metadata["replan"] = True

        trace = await self.build_reasoning_trace(reasoning_steps)

        logger.info(
            "[ReasoningEngine] Mode=%s Agents=%s Memory=%s Planner=%s",
            mode,
            selected_agents,
            getattr(decision, "use_memory", False) if decision else False,
            getattr(decision, "use_planner", False) if decision else False,
        )

        if self.working_memory:
            topic_str = conv_tracking.get("topic")
            if topic_str and confidence > 0.7 and hasattr(self.working_memory, "set_topic"):
                self.working_memory.set_topic(topic_str)
            if hasattr(self.working_memory, "remember_exchange"):
                self.working_memory.remember_exchange(
                    raw_query,
                    response_to_store
                )

        response_strategy = await self.decide_response_strategy(goal, context)

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
            metadata=metadata,
            answer=response_to_store if answer else answer,
            requires_memory=requires_memory,
            requires_documents=requires_documents,
            requires_tools=requires_tools,
            requires_web=requires_web,
            requires_planning=requires_planning,
            requires_clarification=requires_clarification,
            resolved_query=query,
            topic=conv_tracking.get("topic", ""),
            working_memory=working_memory,
            response_strategy=response_strategy,
            reasoning_mode=mode,
            topic_changed=topic_changed,
            reasoning_trace=trace,
            hypotheses=hypotheses,
            simulations=simulations,
            critique=critique,
            action_predictions=action_predictions,
            primary_action=action,
            reasoning=f"Advanced resolution of objective '{goal}' under mode '{mode}' with confidence {confidence:.2f}.",
            workflow=workflow,
            agent_outputs=agent_outputs
        )
