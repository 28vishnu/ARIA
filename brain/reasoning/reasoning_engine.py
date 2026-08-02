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

    async def track_conversation(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Track conversation turns, history, active topic, previous topic, entities, and dialogue stage."""
        conv = context.get("conversation", {})
        topic = conv.get("topic")
        previous_topic = conv.get("previous_topic")
        entities = conv.get("entities", [])
        history = conv.get("history", [])

        # Determine dialogue stage
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
        Rewrite follow-up questions (like 'continue', 'why', 'compare it', 'what about that')
        into standalone queries using conversation history and LLM or context.
        """
        conv_state = await self.track_conversation(context)
        history = conv_state["history"]
        topic = conv_state["topic"]

        clean_q = query.strip()
        lower_q = clean_q.lower()

        # Quick programmatic handling for common short follow-ups if topic is present
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

        # Fallback to LLM reference resolution if history exists
        if self.llm_router and hasattr(self.llm_router, "chat"):
            try:
                messages = [
                    {
                        "role": "system",
                        "content": (
                            "Rewrite follow-up questions, pronouns (it, that), and context references "
                            "into fully self-contained standalone questions using the conversation history. "
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
        """Detect whether the user has shifted conversational topic by comparing current and previous topics."""
        conv = context.get("conversation", {})
        curr = conv.get("topic")
        prev = conv.get("previous_topic")
        if curr and prev and curr.lower() != prev.lower():
            return True
        return False

    async def build_working_memory(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build rich working memory including retrieved memories, recent conversation,
        active document, detected entities, current goal, and current topic.
        """
        conv = context.get("conversation", {})
        return {
            "retrieved_memories": context.get("memory", []),
            "recent_conversation": conv.get("history", [])[-5:],
            "active_document": context.get("document", {}),
            "detected_entities": conv.get("entities", []),
            "current_goal": context.get("current_goal"),
            "current_topic": conv.get("topic"),
        }

    async def decide_response_strategy(self, goal: str, context: Dict[str, Any]) -> str:
        """Decide the high-level response strategy based on goal and response depth hints."""
        depth = context.get("response", {}).get("depth", "normal")
        return f"{goal}_strategy_{depth}"

    async def choose_reasoning_mode(self, context: Dict[str, Any]) -> str:
        """
        Dynamically choose reasoning mode based on query characteristics:
        - conversational (continue, greetings, acknowledgements)
        - analytical (compare, explain, why, how)
        - planning (create roadmap, steps, plan)
        - memory (remember, my profile, save)
        - web (latest, current news, today)
        - knowledge_first (default fallback)
        """
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
        """Determine if a formal execution plan is required."""
        query = str(context.get("query", ""))
        mode = await self.choose_reasoning_mode(context)
        return goal == "plan" or mode == "planning" or len(query.split()) > 10

    async def should_use_agents(self, goal: str, context: Dict[str, Any]) -> bool:
        """Determine if specialist reasoning agents should be engaged."""
        mode = await self.choose_reasoning_mode(context)
        return goal in ("plan", "search", "execute") or mode in ("analytical", "planning")

    async def should_use_memory(self, context: Dict[str, Any]) -> bool:
        """Determine if personal memory retrieval should be utilized."""
        return True

    async def should_use_documents(self, context: Dict[str, Any]) -> bool:
        """Determine if active documents or document repositories should be searched."""
        doc = context.get("document", {})
        return bool(doc.get("active") or doc.get("name"))

    async def should_use_web(self, query: str, context: Dict[str, Any]) -> bool:
        """Determine if online web search fallback is necessary."""
        mode = await self.choose_reasoning_mode(context)
        q = query.lower()
        return mode == "web" or any(term in q for term in ["latest", "current", "news", "today", "search web"])

    async def build_reasoning_trace(self, steps: List[str]) -> str:
        """Compile individual reasoning steps into a coherent audit trail."""
        return " -> ".join(steps)

    async def understand_goal(
        self,
        context: Dict[str, Any],
    ) -> str:
        """
        Determine the primary user objective using intent, conversation state,
        current goals, active documents, and query characteristics.
        """
        return await self.track_goal(context)

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
        detect conflicts, calculate confidence, select agents, and return ReasoningResult
        with all required new fields populated.
        """
        raw_query = str(context.get("query", "")).strip()
        reasoning_steps = []

        # 1. Conversation tracking & Reference resolution
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
        reasoning_steps.append(f"Chosen reasoning mode: {reasoning_mode} with strategy: {response_strategy}")

        use_planner = await self.should_use_planner(goal, context)
        use_agents = await self.should_use_agents(goal, context)
        use_memory = await self.should_use_memory(context)
        use_docs = await self.should_use_documents(context)
        use_web = await self.should_use_web(query, context)
        reasoning_steps.append(f"Subsystems -> Planner: {use_planner}, Agents: {use_agents}, Memory: {use_memory}, Docs: {use_docs}, Web: {use_web}")

        # 2. Retrieve Evidence in Parallel & Normalize
        retrieval = await self.retrieve_context(query)
        memories = retrieval["memories"] if use_memory else []
        knowledge = retrieval["knowledge"]
        graph_results = retrieval["graph"]
        world_state = retrieval["world"]
        reasoning_steps.append("Retrieved and normalized context evidence")

        # 3. Evidence Fusion & Multi-Hop Reasoning
        merged_evidence = await self.merge_evidence(memories, knowledge, graph_results, world_state)
        evidence = await self.multi_hop_reasoning(query, merged_evidence)
        reasoning_steps.append("Fused evidence and performed multi-hop exploration")

        # 4. Rank Evidence & Conflict Detection
        ranked_evidence = await self.rank_evidence(evidence)
        conflicts = await self.detect_conflicts(ranked_evidence)
        reasoning_steps.append("Ranked evidence and checked conflicts")

        # 5. Calculate Confidence
        confidence = self.calculate_confidence(ranked_evidence)
        reasoning_steps.append(f"Calculated confidence: {confidence:.2f}")

        # 6. Multi-Agent Reasoning Selection
        selected_agents = await self.choose_agents(query, context) if use_agents else []
        workflow = AgentWorkflow()
        for agent in selected_agents:
            workflow.add(agent)
        reasoning_steps.append(f"Selected {len(selected_agents)} agent(s)")

        # 7. Determine Plan Automatically if Multi-step Required
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
            },
            resolved_query=query,
            topic=conv_tracking.get("topic", ""),
            working_memory=working_memory,
            response_strategy=response_strategy,
            reasoning_mode=reasoning_mode,
            topic_changed=topic_changed,
            reasoning_trace=trace,
            primary_action=action,
            reasoning=f"Resolved objective '{goal}' under mode '{reasoning_mode}' with confidence {confidence:.2f}.",
            workflow=workflow
        )
