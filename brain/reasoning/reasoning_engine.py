import logging
import asyncio
import time
import re
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

from brain.agents.agent_workflow import AgentWorkflow
from brain.intent.intent_analyzer import IntentAnalyzer

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
        self.intent_analyzer = IntentAnalyzer(llm_router=llm_router)

        # Multi-topic conversation state
        self.conversation_threads = {}
        self.active_thread_id = None

    def _empty_reasoning_result(
        self,
        *,
        goal: str = "answer",
        action: str = "chat",
        confidence: float = 0.5,
        answer: Optional[str] = None,
    ) -> ReasoningResult:
        return ReasoningResult(
            goal=goal,
            action=action,
            confidence=confidence,
            evidence=[],
            selected_agents=[],
            plan=[],
            retrieved_memory=[],
            retrieved_knowledge=[],
            graph_results=[],
            world_state={},
            answer=answer,
        )

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
    ) -> str:
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

    def choose_best_agents(
        self,
        query: str,
        intent_name: Optional[str] = None,
    ) -> List[str]:
        """
        Select the specialist capabilities required for the request.

        Intent is the primary signal.
        Keyword matching is used only as a secondary fallback so that
        multi-purpose requests can still select more than one capability.
        """

        query = str(query or "").strip().lower()
        intent_name = str(intent_name or "").strip().lower()

        agents = []

        intent_agent_map = {
            "memory": "memory",
            "memory_store": "memory",
            "memory_update": "memory",
            "memory_delete": "memory",

            "document": "document",
            "document_search": "document",
            "document_query": "document",
            "delete_document": "document",
            "delete_all_documents": "document",

            "search": "research",
            "research": "research",

            "planner": "planning",
            "planning": "planning",

            "coding": "coding",
            "code": "coding",

            "writing": "writing",

            "greeting": "chat",
            "question": "chat",
            "chat": "chat",
            "conversation": "chat",
        }

        primary_agent = intent_agent_map.get(intent_name)

        if primary_agent:
            agents.append(primary_agent)

        if any(word in query for word in [
            "code",
            "python",
            "java",
            "javascript",
            "typescript",
            "bug",
            "debug",
            "program",
            "implement",
            "function",
            "class",
            "api",
        ]):
            agents.append("coding")

        if any(word in query for word in [
            "research",
            "find",
            "search",
            "compare",
            "latest",
            "news",
            "current",
            "recent",
            "today",
            "look up",
        ]):
            agents.append("research")

        if any(word in query for word in [
            "plan",
            "planning",
            "roadmap",
            "steps",
            "schedule",
            "strategy",
            "build",
            "create",
        ]):
            agents.append("planning")

        if any(word in query for word in [
            "write",
            "essay",
            "email",
            "story",
            "article",
            "rewrite",
            "summary",
        ]):
            agents.append("writing")

        if any(word in query for word in [
            "remember",
            "recall",
            "save this",
            "store this",
            "forget this",
            "delete memory",
        ]):
            agents.append("memory")

        if any(word in query for word in [
            "document",
            "pdf",
            "file",
            "uploaded file",
            "this file",
        ]):
            agents.append("document")

        if not agents:
            agents.append("chat")

        unique_agents = list(dict.fromkeys(agents))

        logger.info(
            "[ReasoningEngine] Intent=%s -> Selected agents=%s",
            intent_name,
            unique_agents,
        )

        return unique_agents

    def build_execution_plan(
        self,
        agents: List[str],
        intent_name: Optional[str] = None,
        goal: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Convert selected capabilities into a deterministic execution plan.
        """

        plan = []

        priority = {
            "memory": 10,
            "document": 20,
            "research": 30,
            "coding": 40,
            "planning": 50,
            "writing": 60,
            "chat": 70,
        }

        for agent in agents:
            plan.append({
                "agent": agent,
                "priority": priority.get(agent, 100),
                "intent": intent_name,
                "goal": goal,
                "status": "pending",
            })

        plan.sort(key=lambda item: item["priority"])

        return plan

    def _normalize_topic(self, value: Any) -> str:
        """Normalize a topic/subject for safe thread matching."""
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        return text.strip(" .,!?:;")

    _CONTEXT_ARTIFACT_WORDS = {
        "context",
        "previous context",
        "current context",
        "active context",
    }

    def _is_context_artifact(self, value: Any) -> bool:
        """Return True when a value is internal context metadata, not a real entity/topic."""
        if value is None:
            return True

        text = re.sub(r"\s+", " ", str(value)).strip().strip(".,:;!?")
        if not text:
            return True

        normalized = text.lower()

        if normalized in self._CONTEXT_ARTIFACT_WORDS:
            return True

        if normalized.endswith(" context"):
            return True

        return False

    def _clean_context_text(self, value: Any) -> str:
        """Remove internal Context: annotations from generated/resolved text."""
        text = str(value or "").strip()

        if not text:
            return ""

        text = re.sub(
            r"\s*Context:\s*[^.!?\n]+[.!?]?",
            "",
            text,
            flags=re.IGNORECASE,
        )

        text = re.sub(r"\s+", " ", text).strip()

        return text

    def _clean_entities(self, values: Optional[List[Any]]) -> List[str]:
        """Normalize entities while rejecting internal context artifacts."""
        cleaned = []

        for value in values or []:
            entity = self._normalize_topic(value)

            if not entity:
                continue

            if self._is_context_artifact(entity):
                continue

            if entity not in cleaned:
                cleaned.append(entity)

        return cleaned

    def _extract_comparison_entities(
        self,
        query: str,
        existing_entities: Optional[List[str]] = None,
    ) -> List[str]:
        """
        Detect entities explicitly being compared in the current request.

        This is intentionally lightweight. It preserves explicit comparison
        state without allowing long-term memory to hijack the conversation.
        """

        entities = list(existing_entities or [])
        text = str(query or "").strip()

        if not text:
            return self._clean_entities(entities)

        comparison_patterns = [
            r"\bbetween\s+(.+?)\s+and\s+(.+?)(?:[?.!,]|$)",
            r"\bcompare\s+(.+?)\s+(?:and|vs\.?|versus)\s+(.+?)(?:[?.!,]|$)",
            r"\b(.+?)\s+(?:vs\.?|versus)\s+(.+?)(?:[?.!,]|$)",
        ]

        for pattern in comparison_patterns:
            match = re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            )

            if not match:
                continue

            left = match.group(1).strip()
            right = match.group(2).strip()

            for value in (left, right):
                value = re.sub(
                    r"\s+",
                    " ",
                    value,
                ).strip(" .,!?:;")

                if value and len(value) <= 100:
                    entities.append(value)

            break

        return self._clean_entities(entities)

    # ================================================================
    # CONVERSATION THREAD HELPERS
    # ================================================================

    _EXPLICIT_TOPIC_PATTERNS = (
        r"^\s*what is\s+(.+?)\s*\??\s*$",
        r"^\s*what are\s+(.+?)\s*\??\s*$",
        r"^\s*who is\s+(.+?)\s*\??\s*$",
        r"^\s*who are\s+(.+?)\s*\??\s*$",
        r"^\s*define\s+(.+?)\s*\??\s*$",
        r"^\s*explain\s+(.+?)\s*\??\s*$",
    )

    _THREAD_RETURN_PATTERNS = (
        r"\bgo back to\s+(.+?)\s*$",
        r"\breturn to\s+(.+?)\s*$",
        r"\bback to\s+(.+?)\s*$",
        r"\bcontinue\s+(?:the\s+)?(.+?)\s+(?:topic|discussion)\s*$",
        r"\bcontinue\s+with\s+(.+?)\s*$",
    )

    _CONTEXTUAL_FOLLOWUPS = (
        "why is it important",
        "why is this important",
        "why are they important",
        "why is that important",
        "why does it matter",
        "why does this matter",
        "how does it work",
        "how does it work?",
        "how does it replicate",
        "how does this work",
        "what about it",
        "tell me more",
        "explain more",
        "more about it",
        "continue",
        "and then",
        "what happens next",
        "how",
        "why",
        "what about",
        "which one",
        "which is better",
        "which is faster",
        "which is easier",
        "which would you choose",
    )

    def _derive_active_topic_from_history(self, history: List[Any], current_query: str = "") -> str:
        if not isinstance(history, list):
            return ""

        for item in reversed(history):
            if not isinstance(item, dict):
                continue

            user_text = self._normalize_topic(
                item.get("user") or item.get("query") or item.get("content") or ""
            )
            if not user_text:
                continue

            explicit = self._extract_explicit_topic(user_text)
            if explicit:
                return explicit

            if self._is_contextual_followup(user_text):
                continue

            if len(user_text.split()) >= 2:
                return user_text

        return ""

    def _sanitize_response_text(self, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""

        text = re.sub(
            r"\b(?:ARIA)?CODEBLOCKPLACEHOLDER\d*\b",
            "",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"\b(?:CODE_BLOCK|CODEBLOCK|RESPONSE_PLACEHOLDER)_PLACEHOLDER\d*\b",
            "",
            text,
            flags=re.IGNORECASE,
        )

        text = re.sub(
            r"\s*Context:\s*[^.!?\n]+[.!?]?",
            "",
            text,
            flags=re.IGNORECASE,
        )

        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _extract_explicit_topic(self, query: str) -> Optional[str]:
        text = self._normalize_topic(query)

        for pattern in self._EXPLICIT_TOPIC_PATTERNS:
            match = re.match(
                pattern,
                text,
                flags=re.IGNORECASE,
            )
            if match:
                topic = self._normalize_topic(match.group(1))
                if topic:
                    return topic

        return None

    def _extract_explicit_subject_from_question(
        self,
        query: str,
    ) -> Optional[str]:
        """
        Detect an explicitly named subject in common question forms.

        Examples:
            Why is DNA important? -> DNA
            Why does DNA matter? -> DNA
            How does DNA replicate? -> DNA
            How does photosynthesis work? -> photosynthesis

        Pronoun-only questions remain contextual:
            Why is it important? -> None
            How does it work? -> None
        """
        text = self._normalize_topic(query)

        patterns = (
            r"^\s*why\s+is\s+(.+?)\s+important\s*\??\s*$",
            r"^\s*why\s+does\s+(.+?)\s+matter\s*\??\s*$",
            r"^\s*how\s+does\s+(.+?)\s+(?:replicate|work)\s*\??\s*$",
            r"^\s*how\s+does\s+(.+?)\s+function\s*\??\s*$",
            r"^\s*what\s+is\s+the\s+importance\s+of\s+(.+?)\s*\??\s*$",
        )

        for pattern in patterns:
            match = re.match(
                pattern,
                text,
                flags=re.IGNORECASE,
            )

            if not match:
                continue

            subject = self._normalize_topic(match.group(1))

            if not subject:
                continue

            if subject.lower() in {
                "it",
                "this",
                "that",
                "they",
                "them",
                "he",
                "she",
                "these",
                "those",
            }:
                return None

            return subject

        return None

    def _extract_thread_return_target(self, query: str) -> Optional[str]:
        text = self._normalize_topic(query)

        for pattern in self._THREAD_RETURN_PATTERNS:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                target = self._normalize_topic(match.group(1))
                if target:
                    return target

        return None

    def _is_contextual_followup(self, query: str) -> bool:
        text = self._normalize_topic(query).lower()

        if not text:
            return False

        if text in self._CONTEXTUAL_FOLLOWUPS:
            return True

        if re.search(
            r"\b(it|this|that|they|them|he|she|these|those)\b",
            text,
            flags=re.IGNORECASE,
        ):
            return True

        if len(text.split()) <= 6 and re.match(
            r"^(why|how|what|which|when|where|who)\b",
            text,
            flags=re.IGNORECASE,
        ):
            return True

        return False

    def _find_thread_by_topic(
        self,
        target: str,
    ) -> Optional[Dict[str, Any]]:
        target_norm = self._normalize_topic(target).lower()

        if not target_norm:
            return None

        for thread in self.conversation_threads.values():
            topic = self._normalize_topic(
                thread.get("topic")
            ).lower()

            subject = self._normalize_topic(
                thread.get("subject")
            ).lower()

            if target_norm == topic or target_norm == subject:
                return thread

        for thread in self.conversation_threads.values():
            topic = self._normalize_topic(
                thread.get("topic")
            ).lower()

            subject = self._normalize_topic(
                thread.get("subject")
            ).lower()

            if (
                target_norm in topic
                or target_norm in subject
                or topic in target_norm
                or subject in target_norm
            ):
                return thread

        return None

    def _get_or_create_thread(
        self,
        topic: Optional[str],
        subject: Optional[str],
        entities: Optional[List[str]] = None,
        force_new: bool = False,
    ) -> Dict[str, Any]:
        topic = self._normalize_topic(topic)
        subject = self._normalize_topic(subject or topic)

        entities = self._clean_entities(entities)

        base_key = (
            topic.lower()
            or subject.lower()
            or "general"
        )

        thread_key = base_key

        if force_new:
            suffix = 2

            while thread_key in self.conversation_threads:
                thread_key = f"{base_key}#{suffix}"
                suffix += 1

        if thread_key not in self.conversation_threads:
            self.conversation_threads[thread_key] = {
                "thread_id": thread_key,
                "topic": topic or subject or "general",
                "subject": subject or topic or "general",

                "previous_topic": None,

                "entities": list(dict.fromkeys(entities)),

                "compared_entities": [],
                "active_comparison": False,

                "history": [],
                "last_user": None,
                "last_assistant": None,
                "last_result": None,

                "turn_count": 0,
                "last_query": None,
                "last_resolved_query": None,
            }

        thread = self.conversation_threads[thread_key]

        if entities:
            thread["entities"] = list(
                dict.fromkeys(
                    thread.get("entities", []) + entities
                )
            )

        self.active_thread_id = thread_key

        return thread

    async def track_conversation(
        self,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        conv = context.get("conversation", {})

        if not isinstance(conv, dict):
            conv = {}

        history = conv.get(
            "conversation_history",
            conv.get("history", []),
        )

        if not isinstance(history, list):
            history = []

        current_query = self._normalize_topic(
            context.get("query", "")
        )

        history_active_topic = self._derive_active_topic_from_history(
            history, current_query
        )

        external_active_topic = self._normalize_topic(
            conv.get("active_topic")
            or conv.get("topic")
            or context.get("topic")
            or history_active_topic
        )

        external_subject = self._normalize_topic(
            conv.get("active_subject")
            or context.get("active_subject")
            or external_active_topic
        )

        external_entities = conv.get(
            "active_entities",
            conv.get("entities", []),
        )

        if not isinstance(external_entities, list):
            external_entities = []

        external_entities = self._clean_entities(external_entities)

        explicit_topic = self._extract_explicit_topic(
            current_query
        )

        explicit_subject = self._extract_explicit_subject_from_question(
            current_query
        )

        if explicit_subject and not explicit_topic:
            explicit_topic = explicit_subject

        return_target = self._extract_thread_return_target(
            current_query
        )

        current_comparison_entities = (
            self._extract_comparison_entities(
                current_query
            )
        )

        thread = None

        if return_target:
            thread = self._find_thread_by_topic(
                return_target
            )

            if thread:
                logger.info(
                    "[Reasoning] Explicitly returning to thread: %s",
                    thread.get("thread_id"),
                )

        if explicit_topic:
            old_active_topic = self._normalize_topic(
                self.conversation_threads.get(
                    self.active_thread_id,
                    {}
                ).get("topic")
            ) if self.active_thread_id else ""

            if not thread:
                thread = self._get_or_create_thread(
                    topic=explicit_topic,
                    subject=explicit_topic,
                    entities=external_entities,
                )

            comparison_is_about_new_topic = (
                len(current_comparison_entities) >= 2
                and any(
                    explicit_topic.lower() in
                    str(entity).lower()
                    or str(entity).lower() in
                    explicit_topic.lower()
                    for entity in current_comparison_entities
                )
            )

            if comparison_is_about_new_topic:
                thread["compared_entities"] = (
                    current_comparison_entities
                )
                thread["active_comparison"] = True
            else:
                thread["compared_entities"] = []
                thread["active_comparison"] = False

            thread["topic"] = explicit_topic
            thread["subject"] = explicit_topic

            if (
                old_active_topic
                and old_active_topic.lower() != explicit_topic.lower()
            ):
                thread["previous_topic"] = old_active_topic

                logger.info(
                    "[Reasoning] Topic shift: %s -> %s",
                    old_active_topic,
                    explicit_topic,
                )

        elif len(current_comparison_entities) >= 2:
            comparison_topic = " vs ".join(
                current_comparison_entities
            )

            thread = self._get_or_create_thread(
                topic=comparison_topic,
                subject=comparison_topic,
                entities=current_comparison_entities,
            )

            thread["compared_entities"] = (
                current_comparison_entities
            )
            thread["active_comparison"] = True

        elif self._is_contextual_followup(current_query):
            if self.active_thread_id:
                thread = self.conversation_threads.get(
                    self.active_thread_id
                )

            if not thread and external_active_topic:
                thread = self._get_or_create_thread(
                    topic=external_active_topic,
                    subject=external_subject or external_active_topic,
                    entities=external_entities,
                )

        else:
            topic = (
                external_active_topic
                or external_subject
                or "general"
            )

            thread = self._get_or_create_thread(
                topic=topic,
                subject=external_subject or topic,
                entities=external_entities,
            )

        if not thread:
            thread = self._get_or_create_thread(
                topic=external_active_topic or "general",
                subject=external_subject or external_active_topic or "general",
                entities=external_entities,
            )

        if explicit_topic:
            if not (
                len(current_comparison_entities) >= 2
                and thread.get("active_comparison")
            ):
                thread["compared_entities"] = []
                thread["active_comparison"] = False

        thread["turn_count"] = (
            int(thread.get("turn_count", 0)) + 1
        )

        thread["last_query"] = current_query

        return {
            "history": history,
            "recent_history": history[-10:],

            "thread_id": thread.get("thread_id"),
            "thread": thread,
            "threads": self.conversation_threads,

            "active_topic": thread.get("topic"),
            "previous_topic": (
                thread.get("previous_topic")
                or (
                    None
                    if self._is_context_artifact(
                        conv.get("previous_topic")
                        or context.get("previous_topic")
                    )
                    else self._normalize_topic(
                        conv.get("previous_topic")
                        or context.get("previous_topic")
                    )
                )
            ),

            "active_subject": thread.get("subject"),

            "active_entities": self._clean_entities(
                thread.get("entities", [])
            ),

            "compared_entities": self._clean_entities(
                thread.get("compared_entities", [])
            ),

            "active_comparison": bool(
                thread.get("active_comparison", False)
            ),

            "last_user": thread.get(
                "last_user"
            ) or conv.get("last_user"),

            "last_assistant": thread.get(
                "last_assistant"
            ) or conv.get("last_assistant"),

            "last_result": thread.get(
                "last_result"
            ) or conv.get("last_result"),

            "dialogue_stage": (
                "greeting"
                if len(history) <= 1
                else "ongoing"
            ),
        }

    async def resolve_references(
        self,
        query: str,
        context: Dict[str, Any],
    ) -> str:
        """
        Resolve contextual references such as:
            "Why is it important?" -> "Why is photosynthesis important?"
            "How does it replicate?" -> "How does DNA replicate?"

        Explicit topics always take priority over previous conversation topics.
        """

        clean_query = self._normalize_topic(query)

        if not clean_query:
            return clean_query

        conversation_state = context.get("conversation_state")

        if not conversation_state:
            conversation_state = await self.track_conversation(context)

        active_thread = conversation_state.get("thread") or {}

        active_topic = self._normalize_topic(
            active_thread.get("topic")
            or conversation_state.get("active_topic")
            or context.get("active_topic")
            or context.get("topic")
        )

        active_subject = self._normalize_topic(
            active_thread.get("subject")
            or conversation_state.get("active_subject")
            or context.get("active_subject")
            or active_topic
        )

        # ---------------------------------------------------------
        # 1. Explicit topic = NEVER replace it with old context
        # ---------------------------------------------------------
        explicit_topic = self._extract_explicit_topic(clean_query)

        if explicit_topic:
            logger.info(
                "[Reasoning] Explicit topic detected: %s",
                explicit_topic,
            )
            return clean_query

        # ---------------------------------------------------------
        # 2. Explicitly returning to another thread
        # ---------------------------------------------------------
        return_target = self._extract_thread_return_target(clean_query)

        if return_target:
            target_thread = self._find_thread_by_topic(return_target)

            if target_thread:
                logger.info(
                    "[Reasoning] Returning to topic: %s",
                    target_thread.get("topic"),
                )

            return clean_query

        # ---------------------------------------------------------
        # 3. No topic available -> leave query unchanged
        # ---------------------------------------------------------
        if not active_topic:
            logger.info(
                "[Reasoning] No active topic available for reference resolution."
            )
            return clean_query

        # ---------------------------------------------------------
        # 4. Contextual follow-up resolution
        # ---------------------------------------------------------
        if self._is_contextual_followup(clean_query):

            resolved = clean_query

            # Pronoun references
            resolved = re.sub(
                r"\bit\b",
                active_topic,
                resolved,
                flags=re.IGNORECASE,
            )

            resolved = re.sub(
                r"\bthis\b",
                active_topic,
                resolved,
                flags=re.IGNORECASE,
            )

            resolved = re.sub(
                r"\bthat\b",
                active_topic,
                resolved,
                flags=re.IGNORECASE,
            )

            # Common implicit follow-ups that contain no explicit subject.
            normalized = clean_query.lower().strip(" ?.!")

            if normalized == "why is it important":
                resolved = f"Why is {active_topic} important?"

            elif normalized == "why is this important":
                resolved = f"Why is {active_topic} important?"

            elif normalized == "why is that important":
                resolved = f"Why is {active_topic} important?"

            elif normalized == "why does it matter":
                resolved = f"Why does {active_topic} matter?"

            elif normalized == "why does this matter":
                resolved = f"Why does {active_topic} matter?"

            elif normalized == "how does it work":
                resolved = f"How does {active_topic} work?"

            elif normalized == "how does this work":
                resolved = f"How does {active_topic} work?"

            elif normalized == "how does it replicate":
                resolved = f"How does {active_topic} replicate?"

            elif normalized == "how does this replicate":
                resolved = f"How does {active_topic} replicate?"

            elif normalized == "tell me more":
                resolved = f"Tell me more about {active_topic}."

            elif normalized == "explain more":
                resolved = f"Explain more about {active_topic}."

            elif normalized == "more about it":
                resolved = f"Tell me more about {active_topic}."

            elif normalized == "what about it":
                resolved = f"What about {active_topic}?"

            elif normalized == "what about this":
                resolved = f"What about {active_topic}?"

            elif normalized == "continue":
                resolved = f"Continue explaining {active_topic}."

            elif normalized == "and then":
                resolved = f"What happens next with {active_topic}?"

            elif normalized == "what happens next":
                resolved = f"What happens next with {active_topic}?"

            resolved = self._clean_context_text(resolved)

            logger.info(
                "[Reasoning] Reference resolved: %r -> %r",
                clean_query,
                resolved,
            )

            return resolved

        # ---------------------------------------------------------
        # 5. Non-contextual query
        # ---------------------------------------------------------
        return clean_query

    async def track_goal(self, context: Dict[str, Any]) -> str:
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
        conv = context.get("conversation", {})
        curr = conv.get("topic")
        prev = conv.get("previous_topic")
        if curr and prev and str(curr).lower() != str(prev).lower():
            return True
        return False

    async def build_working_memory(
        self,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        conversation_state = await self.track_conversation(context)
        active_thread = conversation_state.get(
            "thread",
            {}
        )

        return {
            "current_query": context.get("query", ""),

            "retrieved_memories": context.get(
                "memory",
                [],
            ),

            "recent_conversation": (
                active_thread.get("history", [])
            ),

            "active_document": (
                context.get("document")
                or context.get("active_document")
                or {}
            ),

            "active_thread_id": (
                conversation_state.get("thread_id")
            ),

            "active_topic": (
                active_thread.get("topic")
            ),

            "previous_topic": (
                conversation_state.get("previous_topic")
            ),

            "active_subject": (
                active_thread.get("subject")
            ),

            "active_entities": (
                active_thread.get("entities", [])
            ),

            "compared_entities": (
                active_thread.get(
                    "compared_entities",
                    []
                )
            ),

            "active_comparison": bool(
                active_thread.get(
                    "active_comparison",
                    False
                )
            ),

            "available_threads": list(
                conversation_state.get(
                    "threads",
                    {}
                ).keys()
            ),

            "current_goal": context.get(
                "current_goal"
            ),

            "resolved_query": context.get(
                "resolved_query",
                context.get("query", ""),
            ),
        }

    async def generate_hypotheses(self, query: str, evidence: List[Dict[str, Any]]) -> List[str]:
        if not query:
            return []
        return [
            f"Hypothesis A: Direct factual fulfillment of '{query}' using retrieved context.",
            f"Hypothesis B: Comprehensive multi-step exploration or workflow expansion for '{query}'."
        ]

    async def simulate_future(self, plan: List[Any], action: str) -> List[Dict[str, Any]]:
        return [
            {"path": action, "projected_success": 0.91, "risk": "low"},
            {"path": "fallback_llm", "projected_success": 0.75, "risk": "medium"}
        ]

    async def self_critique(self, hypotheses: List[str], evidence: List[Dict[str, Any]]) -> Dict[str, Any]:
        return {
            "valid": True,
            "flaws": [],
            "recommendation": "Proceed with primary path with high confidence."
        }

    async def confidence_score(self, evidence: List[Dict[str, Any]], critique: Dict[str, Any]) -> float:
        base = 0.75 if not evidence else sum(item.get("confidence", 0.5) for item in evidence) / len(evidence)
        return min(1.0, base + (0.15 if critique.get("valid") else 0.0))

    async def action_prediction(self, goal: str, context: Dict[str, Any]) -> List[str]:
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
        if simulations:
            best = max(simulations, key=lambda s: s.get("projected_success", 0.0))
            return best.get("path", "primary")
        return hypotheses[0] if hypotheses else "default"

    async def decide_response_strategy(self, goal: str, context: Dict[str, Any]) -> Dict[str, Any]:
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

    async def needs_clarification(
        self,
        query: str,
        context: Dict[str, Any],
    ) -> bool:
        clean = self._normalize_topic(query)

        if not clean:
            return True

        if self._is_contextual_followup(clean):
            conversation_state = context.get("conversation_state") or {}

            active_thread = conversation_state.get("thread") or {}
            active_topic = (
                active_thread.get("topic")
                or conversation_state.get("active_topic")
                or context.get("topic")
            )

            if active_topic:
                return False

            conv = context.get("conversation", {})

            if isinstance(conv, dict):
                if (
                    conv.get("active_topic")
                    or conv.get("topic")
                    or conv.get("history")
                    or conv.get("conversation_history")
                ):
                    return False

            return True

        if len(clean.split()) <= 1 and clean.lower() not in {
            "hi",
            "hello",
            "help",
            "status",
        }:
            conv = context.get("conversation", {})

            if isinstance(conv, dict):
                if (
                    conv.get("topic")
                    or conv.get("active_topic")
                    or conv.get("history")
                    or conv.get("conversation_history")
                ):
                    return False

            return True

        return False

    async def build_reasoning_trace(self, steps: List[str]) -> str:
        return " -> ".join(steps)

    async def retrieve_context(
        self,
        query: str,
        requires_memory: bool = True,
        conversation_state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        memory_query = query

        if conversation_state:
            context = getattr(
                self,
                "_temp_context",
                {},
            )

            context["conversation_state_for_memory"] = {
                "active_topic": conversation_state.get(
                    "active_topic"
                ),
                "active_subject": conversation_state.get(
                    "active_subject"
                ),
                "active_entities": conversation_state.get(
                    "active_entities",
                    [],
                ),
                "compared_entities": conversation_state.get(
                    "compared_entities",
                    [],
                ),
                "active_comparison": conversation_state.get(
                    "active_comparison",
                    False,
                ),
            }

        async def safe_call(
            operation,
            default,
            timeout=8.0,
            name="retrieval",
        ):
            if operation is None:
                return default

            try:
                return await asyncio.wait_for(
                    operation,
                    timeout=timeout,
                )

            except asyncio.TimeoutError:
                logger.warning(
                    "[ReasoningEngine] %s timed out after %.1fs",
                    name,
                    timeout,
                )
                return default

            except Exception:
                logger.exception(
                    "[ReasoningEngine] %s failed",
                    name,
                )
                return default

        memory_operation = None

        if (
            requires_memory
            and self.memory_router
            and hasattr(
                self.memory_router,
                "recall",
            )
        ):
            memory_operation = self.memory_router.recall(
                memory_query
            )

        knowledge_operation = None

        if self.knowledge_database:

            if hasattr(
                self.knowledge_database,
                "retrieve",
            ):
                knowledge_operation = (
                    self.knowledge_database.retrieve(
                        query
                    )
                )

            elif hasattr(
                self.knowledge_database,
                "search",
            ):
                knowledge_operation = (
                    self.knowledge_database.search(
                        query
                    )
                )

            elif hasattr(
                self.knowledge_database,
                "answer",
            ):
                knowledge_operation = (
                    self.knowledge_database.answer(
                        question=query
                    )
                )

        graph_operation = None

        if (
            self.knowledge_graph
            and hasattr(
                self.knowledge_graph,
                "search",
            )
        ):
            graph_operation = (
                self.knowledge_graph.search(
                    query
                )
            )

        world_operation = None

        if (
            self.world_model
            and hasattr(
                self.world_model,
                "search",
            )
        ):
            world_operation = asyncio.to_thread(
                self.world_model.search,
                query,
            )

        raw_memories, raw_knowledge, raw_graph, raw_world = (
            await asyncio.gather(

                safe_call(
                    memory_operation,
                    [],
                    name="memory retrieval",
                ),

                safe_call(
                    knowledge_operation,
                    [],
                    name="knowledge retrieval",
                ),

                safe_call(
                    graph_operation,
                    [],
                    name="graph retrieval",
                ),

                safe_call(
                    world_operation,
                    {},
                    name="world-model retrieval",
                ),
            )
        )

        memories = []

        memory_items = (
            raw_memories
            if isinstance(raw_memories, list)
            else (
                [raw_memories]
                if raw_memories
                else []
            )
        )

        for item in memory_items:

            content = (
                item.get(
                    "content",
                    str(item),
                )
                if isinstance(item, dict)
                else str(item)
            )

            if not content:
                continue

            memories.append({
                "source": "memory",
                "confidence": (
                    item.get(
                        "confidence",
                        0.95,
                    )
                    if isinstance(item, dict)
                    else 0.95
                ),
                "importance": (
                    item.get(
                        "importance",
                        85,
                    )
                    if isinstance(item, dict)
                    else 85
                ),
                "content": content,
            })

        knowledge = []

        knowledge_items = (
            raw_knowledge
            if isinstance(raw_knowledge, list)
            else (
                [raw_knowledge]
                if raw_knowledge
                else []
            )
        )

        for item in knowledge_items:

            content = (
                item.get(
                    "content",
                    str(item),
                )
                if isinstance(item, dict)
                else str(item)
            )

            if not content:
                continue

            knowledge.append({
                "source": "knowledge_database",
                "confidence": (
                    item.get(
                        "confidence",
                        0.91,
                    )
                    if isinstance(item, dict)
                    else 0.91
                ),
                "importance": (
                    item.get(
                        "importance",
                        50,
                    )
                    if isinstance(item, dict)
                    else 50
                ),
                "content": content,
            })

        graph = []

        graph_items = (
            raw_graph
            if isinstance(raw_graph, list)
            else (
                [raw_graph]
                if raw_graph
                else []
            )
        )

        for item in graph_items:

            content = (
                item.get(
                    "content",
                    str(item),
                )
                if isinstance(item, dict)
                else str(item)
            )

            if not content:
                continue

            graph.append({
                "source": "knowledge_graph",
                "confidence": (
                    item.get(
                        "confidence",
                        0.88,
                    )
                    if isinstance(item, dict)
                    else 0.88
                ),
                "importance": (
                    item.get(
                        "importance",
                        60,
                    )
                    if isinstance(item, dict)
                    else 60
                ),
                "content": content,
            })

        world = {}

        if isinstance(
            raw_world,
            dict,
        ):
            for category, items in raw_world.items():

                if items:
                    world[category] = items

        return {
            "memories": memories,
            "knowledge": knowledge,
            "graph": graph,
            "world": world,
        }

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

    async def detect_conflicts(
        self,
        evidence: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        if not evidence:
            return {
                "conflict": False,
                "sources": [],
                "conflicts": [],
                "confidence": 0.0,
            }

        sources = list(
            dict.fromkeys(
                item.get("source", "unknown")
                for item in evidence
            )
        )

        conflicts = []

        grouped = {}

        for item in evidence:
            content = str(
                item.get("content", "")
            ).strip()

            if not content:
                continue

            subject = str(
                item.get("subject")
                or item.get("topic")
                or ""
            ).strip().lower()

            if not subject:
                subject = re.sub(
                    r"\s+",
                    " ",
                    content[:120].lower(),
                )

            grouped.setdefault(
                subject,
                []
            ).append(item)

        contradiction_pairs = [
            ("true", "false"),
            ("yes", "no"),
            ("enabled", "disabled"),
            ("active", "inactive"),
            ("available", "unavailable"),
            ("supports", "does not support"),
            ("supported", "unsupported"),
            ("increase", "decrease"),
            ("increases", "decreases"),
            ("higher", "lower"),
            ("before", "after"),
        ]

        for subject, items in grouped.items():

            if len(items) < 2:
                continue

            normalized = [
                re.sub(
                    r"\s+",
                    " ",
                    str(item.get("content", "")).lower(),
                )
                for item in items
            ]

            for left_index in range(len(normalized)):
                for right_index in range(
                    left_index + 1,
                    len(normalized),
                ):
                    left = normalized[left_index]
                    right = normalized[right_index]

                    for positive, negative in contradiction_pairs:

                        if (
                            positive in left
                            and negative in right
                        ) or (
                            negative in left
                            and positive in right
                        ):
                            conflicts.append({
                                "subject": subject,
                                "source_a": items[left_index].get(
                                    "source",
                                    "unknown",
                                ),
                                "source_b": items[right_index].get(
                                    "source",
                                    "unknown",
                                ),
                                "type": "explicit_contradiction",
                            })

                            break

        conflict_detected = bool(conflicts)

        if conflict_detected:
            confidence = 0.45
        elif len(sources) >= 2:
            confidence = 0.80
        else:
            confidence = 0.65

        return {
            "conflict": conflict_detected,
            "sources": sources,
            "conflicts": conflicts,
            "confidence": confidence,
        }

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
        completed = []
        failed = []

        async def run(agent):
            agent_name = agent.__class__.__name__

            try:
                if not hasattr(agent, "execute"):
                    failed.append({
                        "agent": agent_name,
                        "error": "Agent has no execute() method",
                    })
                    return

                result = await agent.execute(query, context)

                outputs[agent_name] = result

                completed.append({
                    "agent": agent_name,
                    "result": result,
                })

            except Exception as exc:
                logger.exception(
                    "[ReasoningEngine] Agent execution failed: %s",
                    agent_name,
                )

                failed.append({
                    "agent": agent_name,
                    "error": str(exc),
                })

        await asyncio.gather(
            *(run(agent) for agent in agents)
        )

        return {
            "outputs": outputs,
            "completed": completed,
            "failed": failed,
            "total": len(agents),
            "success_rate": (
                len(completed) / len(agents)
                if agents
                else 0.0
            ),
        }

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

        if not isinstance(response, str) or not response.strip():
            return {
                "goal_completed": False,
                "confidence": 0.0,
                "missing": ["LLM response unavailable"],
            }

        return self.llm_router.extract_json(response)

    async def reason(self, context: Dict[str, Any]) -> ReasoningResult:
        self._temp_context = context
        user_query = str(context.get("query", "")).strip()

        intent = await self.intent_analyzer.analyze(
            user_query
        )

        context["intent"] = intent

        intent_name = (
            intent.intent_type
            if hasattr(intent, "intent_type")
            else str(intent)
        ).lower()
        intent_confidence = getattr(intent, "confidence", 1.0)

        # -----------------------------------------------------
        # EXECUTABLE ACTION
        # -----------------------------------------------------
        if (
            intent_name in ("action", "tool")
            or bool(
                getattr(intent, "data", None)
                and intent.data.get("action_name")
            )
        ):

            intent_data = getattr(
                intent,
                "data",
                {}
            ) or {}

            action_name = intent_data.get(
                "action_name"
            )

            action_params = intent_data.get(
                "action_params",
                {}
            ) or {}

            task_plan = context.get("task_plan", [])
            task_workflows = context.get("task_workflows", {})
            workflow = context.get("workflow")

            return ReasoningResult(
                primary_action="action",
                confidence=intent_confidence,
                reasoning="Executable system action requested.",
                metadata={
                    "goal": "action_execution",
                    "execution_plan": ["action"],
                    "response_depth": "concise",
                    "task_plan": task_plan,
                    "task_workflows": task_workflows,
                },
                action_name=action_name,
                action_params=action_params,
                workflow=workflow,
                goal="action",
                action="action",
                evidence=[],
                selected_agents=[],
                plan=[],
                retrieved_memory=[],
                retrieved_knowledge=[],
                graph_results=[],
                world_state={},
            )

        logger.info(
            "[ReasoningEngine] Intent=%s confidence=%.2f",
            intent.intent_type,
            intent.confidence,
        )

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

        if intent.intent_type == "memory":
            strategy = "memory_first"

        elif intent.intent_type == "document":
            strategy = "document_first"

        elif intent.intent_type == "search":
            strategy = "research_first"

        elif intent.intent_type == "question":
            if intent.requires_reasoning:
                strategy = "deep_reasoning"

        elif intent.intent_type == "greeting":
            strategy = "conversation"

        decision = context.get("decision")

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
        reasoning_steps.append(
            f"Detected intent: {intent.intent_type} "
            f"(confidence={intent.confidence:.2f})"
        )

        conv_tracking = await self.track_conversation(context)
        reasoning_steps.append("Tracked conversation state")

        logger.info(
            "[Conversation DEBUG] query=%r active_thread=%r topic=%r subject=%r history=%d",
            raw_query,
            conv_tracking.get("thread_id"),
            conv_tracking.get("active_topic"),
            conv_tracking.get("active_subject"),
            len(
                conv_tracking.get("thread", {}).get("history", [])
            ),
        )

        context["conversation_state"] = conv_tracking

        resolved_query_raw = await self.resolve_references(
            raw_query,
            {
                **context,
                "conversation_state": conv_tracking,
            },
        )

        logger.info(
            "[Conversation DEBUG] resolved_query=%r",
            resolved_query_raw,
        )

        context["raw_query"] = raw_query
        context["resolved_query"] = self._clean_context_text(resolved_query_raw)
        query = context["resolved_query"]

        context["conversation_state"] = conv_tracking
        context["active_topic"] = conv_tracking.get("active_topic")
        context["active_subject"] = conv_tracking.get("active_subject")
        context["conversation_history"] = conv_tracking.get("recent_history", [])
        context["active_thread_history"] = (
            conv_tracking.get("thread", {}).get("history", [])
        )
        context["contextual_followup"] = self._is_contextual_followup(query)

        reasoning_steps.append(
            "Resolved conversational references"
        )

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

        if mode in (None, "", "knowledge_first", "fast"):
            mode = strategy

        reasoning_steps.append(f"Chosen reasoning mode: {mode}")

        # ---------------------------------------------------------
        # PHASE 2: Intent-driven agent selection + execution
        # ---------------------------------------------------------

        intent_type = getattr(intent, "intent_type", None)

        # Select agents strictly from the detected intent.
        selected_agents = self.choose_best_agents(
            query=query,
            intent_name=intent_type,
        )

        # Add explicitly requested capabilities from the cognitive decision.
        if decision:
            capability_agents = []

            if getattr(decision, "use_memory", False):
                capability_agents.append("memory")

            if getattr(decision, "use_documents", False):
                capability_agents.append("document")

            if getattr(decision, "use_planner", False):
                capability_agents.append("planning")

            if getattr(decision, "use_web", False):
                capability_agents.append("research")

            if getattr(decision, "use_tools", False):
                capability_agents.append("coding")

            for agent_name in capability_agents:
                if agent_name not in selected_agents:
                    selected_agents.append(agent_name)

        # Always have a valid fallback.
        if not selected_agents:
            selected_agents = ["chat"]

        # Remove duplicates while preserving execution order.
        selected_agents = list(dict.fromkeys(selected_agents))

        reasoning_steps.append(
            f"Selected agents from intent={intent_type}: {selected_agents}"
        )

        # Build deterministic execution plan.
        execution_plan = self.build_execution_plan(
            agents=selected_agents,
            intent_name=intent_type,
            goal=goal,
        )

        context["execution_plan"] = execution_plan

        reasoning_steps.append(
            f"Built execution plan with {len(execution_plan)} step(s)"
        )

        # ---------------------------------------------------------
        # Capability flags
        # ---------------------------------------------------------

        requires_planning = (
            getattr(decision, "use_planner", False)
            if decision
            else strategy == "planning_first"
        )

        requires_tools = (
            getattr(decision, "use_tools", False)
            if decision
            else False
        )

        requires_memory = (
            getattr(decision, "use_memory", False)
            if decision
            else strategy == "memory_first"
        )

        requires_documents = (
            getattr(decision, "use_documents", False)
            if decision
            else strategy == "document_first"
        )

        requires_web = (
            getattr(decision, "use_web", False)
            if decision
            else strategy == "research_first"
        )

        # Intent requirements always take priority.
        requires_memory = (
            requires_memory
            or getattr(intent, "requires_memory", False)
        )

        requires_documents = (
            requires_documents
            or getattr(intent, "requires_documents", False)
        )

        requires_web = (
            requires_web
            or getattr(intent, "requires_web", False)
        )

        if getattr(intent, "requires_reasoning", False):
            mode = "deep_reasoning"

        if strategy == "research_first":
            requires_web = True

        reasoning_steps.append(
            f"Capabilities: web={requires_web}, "
            f"memory={requires_memory}, "
            f"planning={requires_planning}, "
            f"tools={requires_tools}"
        )

        # ---------------------------------------------------------
        # Agent execution
        # ---------------------------------------------------------

        agent_results = []

        if self.agent_coordinator and selected_agents:

            execution_plan_payload = {
                "agents": selected_agents,
                "query": query,
                "context": context,
                "plan": execution_plan,
            }

            # Give the Lead Agent the opportunity to optimize ordering.
            if (
                self.lead_agent
                and hasattr(self.lead_agent, "create_execution_plan")
            ):
                try:
                    lead_plan = await self.lead_agent.create_execution_plan(
                        query,
                        context,
                        selected_agents,
                    )

                    if isinstance(lead_plan, dict):
                        execution_plan_payload.update(lead_plan)

                except Exception:
                    logger.exception(
                        "[ReasoningEngine] Lead Agent planning failed; "
                        "using deterministic Phase 2 plan."
                    )

            logger.info(
                "[ReasoningEngine] Phase 2 execution plan: %s",
                execution_plan_payload,
            )

            if hasattr(self.agent_coordinator, "execute"):
                try:
                    coordination = await self.agent_coordinator.execute(
                        execution_plan_payload.get(
                            "agents",
                            selected_agents,
                        ),
                        execution_plan_payload.get(
                            "query",
                            query,
                        ),
                        execution_plan_payload.get(
                            "context",
                            context,
                        ),
                    )

                    if isinstance(coordination, dict):

                        agent_results = coordination.get(
                            "outputs",
                            [],
                        )

                        context.update(
                            coordination.get(
                                "shared_context",
                                {},
                            )
                        )

                        context["execution_result"] = coordination

                except Exception:
                    logger.exception(
                        "[ReasoningEngine] Phase 2 agent coordination failed."
                    )
                    agent_results = []

        context["best_agent"] = (
            agent_results[0].get("agent")
            if agent_results
            and isinstance(agent_results[0], dict)
            else None
        )

        logger.info(
            "[ReasoningEngine] %d agents completed",
            len(agent_results),
        )

        # Normalize specialist-agent outputs.
        workflow = AgentWorkflow()
        agent_outputs = {}

        for result in agent_results:

            if not isinstance(result, dict):
                continue

            agent_name = result.get("agent", "unknown")
            agent_result = result.get("result")

            if agent_result is None:
                agent_result = ""

            confidence_value = result.get("confidence", 0.0)

            try:
                confidence_value = float(confidence_value)
            except (TypeError, ValueError):
                confidence_value = 0.0

            agent_outputs[agent_name] = agent_result

            logger.info(
                "\nAgent: %s\nConfidence: %.2f\n%s\n",
                agent_name,
                confidence_value,
                agent_result,
            )

        reasoning_steps.append(
            f"Executed {len(agent_results)} specialist agent(s) "
            f"via Phase 2 coordinator"
        )

        retrieval = await self.retrieve_context(
            query,
            requires_memory=requires_memory,
            conversation_state=conv_tracking,
        )
        raw_memories = retrieval["memories"] if requires_memory else []
        knowledge = retrieval["knowledge"]
        graph_results = retrieval["graph"]
        world_state = retrieval["world"]
        reasoning_steps.append("Retrieved context evidence")

        memory_summary_parts = []
        for m in raw_memories:
            content = m.get("content", str(m)) if isinstance(m, dict) else str(m)
            memory_summary_parts.append(content)
        memory_summary = ". ".join(memory_summary_parts)

        memories = [{"source": "memory", "confidence": 0.95, "importance": 85, "content": memory_summary}] if memory_summary else []

        merged_evidence = await self.merge_evidence(memories, knowledge, graph_results, world_state)
        evidence = await self.multi_hop_reasoning(query, merged_evidence)
        ranked_evidence = await self.rank_evidence(evidence)

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
                    if isinstance(reply, str) and reply.strip():
                        answer = reply.strip()
                    else:
                        answer = (
                            "Here is the summary of your current "
                            "project and progress."
                        )
                except Exception:
                    answer = f"Current Goal: {getattr(goal_obj, 'title', 'None')} (Progress: {getattr(goal_obj, 'progress', 0.0)}%)"

        action = "chat"
        if goal == "remember" or goal == "delete":
            action = "memory_conversation"
        elif goal == "plan":
            action = "planner"

        # Respect authoritative decision action if provided
        if decision and getattr(decision, "action", None):
            action = decision.action
            if decision.action == "planner":
                requires_planning = True
                if "planning" not in selected_agents:
                    selected_agents.append("planning")

        reasoning_time = round(time.time() - start_time, 3)

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
        response_to_store = self._sanitize_response_text(response_to_store)

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

        response_to_store = self._sanitize_response_text(response_to_store)

        active_thread = conv_tracking.get("thread")

        if active_thread:
            active_thread["last_user"] = raw_query
            active_thread["last_resolved_query"] = query
            active_thread["last_assistant"] = response_to_store
            active_thread["last_result"] = response_to_store

            active_thread.setdefault("history", [])

            active_thread["history"].append({
                "role": "user",
                "content": raw_query,
            })

            active_thread["history"].append({
                "role": "assistant",
                "content": response_to_store,
            })

            active_thread["history"] = (
                active_thread["history"][-20:]
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
            "intent": intent.intent_type,
            "intent_confidence": intent.confidence,
            "intent_requires_memory": intent.requires_memory,
            "intent_requires_documents": intent.requires_documents,
            "intent_requires_web": intent.requires_web,
            "intent_requires_reasoning": intent.requires_reasoning,
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
            "conversation": {
                "active_thread_id": conv_tracking.get("thread_id"),
                "active_topic": conv_tracking.get("active_topic"),
                "active_subject": conv_tracking.get("active_subject"),
                "contextual_followup": self._is_contextual_followup(query),
                "history": conv_tracking.get("recent_history", []),
            },
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
            topic_str = conv_tracking.get("active_topic", conv_tracking.get("topic", ""))
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
            topic=conv_tracking.get(
                "active_topic",
                conv_tracking.get("topic", ""),
            ),
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
