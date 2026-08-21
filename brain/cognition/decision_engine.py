import time
from typing import Any, Dict, List

from brain.models.intent import Intent
from brain.models.context import Context
from brain.models.decision import Decision


class DecisionEngine:
    """
    ARIA's canonical decision layer.

    Converts structured intent + context into one executable decision.

    The DecisionEngine does not execute tools or generate responses.
    It only decides what ARIA should do next.
    """

    def __init__(self):
        self.decision_count = 0

    def decide(
        self,
        intent: Intent,
        context: Context,
    ) -> Decision:

        self.decision_count += 1

        if intent is None:
            return self._fallback_decision()

        intent_type = str(
            getattr(intent, "intent_type", "conversation")
            or "conversation"
        ).lower()

        confidence = float(
            getattr(intent, "confidence", 0.5)
            or 0.5
        )

        confidence = max(
            0.0,
            min(confidence, 1.0),
        )

        requires_memory = bool(
            getattr(intent, "requires_memory", False)
        )

        requires_documents = bool(
            getattr(intent, "requires_documents", False)
        )

        requires_web = bool(
            getattr(intent, "requires_web", False)
        )

        requires_reasoning = bool(
            getattr(intent, "requires_reasoning", False)
        )

        requires_planning = False
        requires_execution = False

        selected_skills: List[str] = []
        selected_tools: List[str] = []
        secondary_actions: List[str] = []

        action = "chat"
        priority = "normal"

        # =========================================================
        # GREETING
        # =========================================================

        if intent_type == "greeting":

            action = "respond"

        # =========================================================
        # MEMORY
        # =========================================================

        elif intent_type in {
            "memory",
            "memory_store",
            "memory_recall",
            "memory_update",
            "memory_delete",
        }:

            action = "memory"

            requires_execution = True
            requires_memory = True

            selected_skills.append(
                "memory_engine"
            )

        # =========================================================
        # DOCUMENT
        # =========================================================

        elif intent_type in {
            "document",
            "document_analysis",
            "document_summary",
        }:

            action = "document"

            requires_execution = True
            requires_documents = True
            requires_reasoning = True

            selected_skills.extend([
                "document_parser",
                "document_intelligence",
            ])

        # =========================================================
        # SEARCH / RESEARCH
        # =========================================================

        elif intent_type in {
            "search",
            "research",
            "web_search",
        }:

            action = "research"

            requires_execution = True
            requires_web = True
            requires_reasoning = True

            selected_skills.append(
                "research"
            )

            selected_tools.append(
                "web_search"
            )

        # =========================================================
        # QUESTION / KNOWLEDGE
        # =========================================================

        elif intent_type in {
            "question",
            "knowledge",
            "factual",
            "explanation",
        }:

            action = "answer"

            requires_execution = True
            requires_reasoning = True

            selected_skills.append(
                "reasoning"
            )

        # =========================================================
        # PLANNING
        # =========================================================

        elif intent_type in {
            "plan",
            "planning",
            "roadmap",
        }:

            action = "plan"

            requires_planning = True
            requires_execution = True
            requires_reasoning = True

            selected_skills.extend([
                "planning",
                "reasoning",
            ])

        # =========================================================
        # CODE / DEVELOPMENT
        # =========================================================

        elif intent_type in {
            "coding",
            "code",
            "programming",
            "development",
        }:

            action = "code"

            requires_execution = True
            requires_reasoning = True

            selected_skills.extend([
                "coding",
                "reasoning",
            ])

        # =========================================================
        # TASK / ACTION
        # =========================================================

        elif intent_type in {
            "task",
            "action",
            "command",
            "automation",
            "execute",
        }:

            action = "execute"

            requires_execution = True
            requires_reasoning = True

            selected_skills.append(
                "execution"
            )

        # =========================================================
        # GENERAL CONVERSATION
        # =========================================================

        else:

            action = "chat"

            # A normal conversation may still require memory.
            if requires_memory:
                selected_skills.append(
                    "memory_engine"
                )

            if requires_reasoning:
                selected_skills.append(
                    "reasoning"
                )

            if requires_web:
                selected_tools.append(
                    "web_search"
                )

                secondary_actions.append(
                    "research"
                )

        # =========================================================
        # INTENT FLAGS OVERRIDE ROUTE DEFAULTS
        # =========================================================

        if requires_memory:
            if "memory_engine" not in selected_skills:
                selected_skills.append(
                    "memory_engine"
                )

        if requires_documents:
            if "document_intelligence" not in selected_skills:
                selected_skills.append(
                    "document_intelligence"
                )

        if requires_reasoning:
            if "reasoning" not in selected_skills:
                selected_skills.append(
                    "reasoning"
                )

        if requires_web:
            if "web_search" not in selected_tools:
                selected_tools.append(
                    "web_search"
                )

        # =========================================================
        # PLANNING HEURISTIC
        # =========================================================

        query = str(
            getattr(intent, "normalized_query", "")
            or ""
        ).lower()

        planning_terms = (
            "build",
            "create",
            "implement",
            "develop",
            "roadmap",
            "plan",
            "steps",
            "design",
            "setup",
            "configure",
        )

        if (
            not requires_planning
            and any(term in query for term in planning_terms)
        ):
            requires_planning = True
            requires_execution = True

            if "planning" not in selected_skills:
                selected_skills.append(
                    "planning"
                )

        # =========================================================
        # PRIORITY
        # =========================================================

        if requires_execution:
            priority = "high"

        if intent_type in {
            "automation",
            "command",
            "execute",
        }:
            priority = "critical"

        # Remove duplicates while preserving order.
        selected_skills = list(
            dict.fromkeys(selected_skills)
        )

        selected_tools = list(
            dict.fromkeys(selected_tools)
        )

        secondary_actions = list(
            dict.fromkeys(secondary_actions)
        )

        return Decision(
            action=action,
            confidence=confidence,
            secondary_actions=secondary_actions,
            data={
                "query": getattr(
                    intent,
                    "original_query",
                    "",
                ),
                "intent_type": intent_type,
            },
            action_name=action,
            action_params={},
            requires_planning=requires_planning,
            requires_execution=requires_execution,
            requires_response=True,
            selected_skills=selected_skills,
            selected_tools=selected_tools,
            selected_plugins=[],
            priority=priority,
            metadata={
                "intent_type": intent_type,
                "requires_memory": requires_memory,
                "requires_documents": requires_documents,
                "requires_web": requires_web,
                "requires_reasoning": requires_reasoning,
                "decision_count": self.decision_count,
            },
            timestamp=time.time(),
        )

    # =========================================================
    # FALLBACK
    # =========================================================

    def _fallback_decision(self) -> Decision:

        return Decision(
            action="chat",
            confidence=0.0,
            requires_planning=False,
            requires_execution=False,
            requires_response=True,
            selected_skills=[],
            selected_tools=[],
            selected_plugins=[],
            priority="normal",
            metadata={
                "fallback": True,
            },
            timestamp=time.time(),
        )