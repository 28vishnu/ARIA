import logging
from typing import Any, Dict

from brain.models.decision import Decision

logger = logging.getLogger("aria")


class DecisionEngine:
    """
    Chooses how ARIA should respond to a user request based on unified context and rich reasoning results.

    It DOES NOT execute anything.
    It only decides what should happen next using the complete execution package.
    """

    def __init__(
        self,
        knowledge_manager=None,
        self_reflection=None,
    ):
        self.knowledge_manager = knowledge_manager
        self.self_reflection = self_reflection

    async def decide(
        self,
        context: Dict[str, Any],
        skill_manager=None,
        planner=None
    ) -> Decision:
        """
        Convert ARIA's advanced reasoning result into the final execution route
        with confidence-based routing, conflict handling, and evidence validation.
        """
        query = str(
            context.get("query", "")
        ).strip()

        reasoning = context.get("reasoning")
        state = context.get("state", {}) or {}
        document = context.get("document", {}) or {}
        conversation = context.get("conversation", {}) or {}

        logger.info(
            "[Decision] Query=%s State=%s",
            query,
            state
        )

        # -----------------------------------------------------
        # 1. REASONING ENGINE IS THE PRIMARY AUTHORITY
        # -----------------------------------------------------

        if reasoning:
            goal = getattr(reasoning, "goal", "answer")
            action = getattr(reasoning, "action", "chat")
            confidence = float(getattr(reasoning, "confidence", 0.80) or 0.80)
            evidence = getattr(reasoning, "evidence", []) or []
            plan = getattr(reasoning, "plan", []) or []
            workflow = getattr(reasoning, "workflow", None)
            metadata = dict(getattr(reasoning, "metadata", {}) or {})
            selected_agents = getattr(reasoning, "selected_agents", []) or []

            conflicts = metadata.get("conflicts", {})
            has_conflict = isinstance(conflicts, dict) and conflicts.get("conflict", False)

            # Package rich execution data payload
            decision_data = {
                "goal": goal,
                "confidence": confidence,
                "evidence": evidence,
                "workflow": workflow,
                "agents": selected_agents,
                "plan": plan,
                "source": metadata.get("source"),
                "reasoning_steps": metadata.get("reasoning_steps"),
                "conflicts": conflicts,
                "reflection_required": confidence < 0.60 or has_conflict,
                **metadata,
            }

            # -------------------------------------------------
            # CONFLICT HANDLING
            # -------------------------------------------------
            if has_conflict:
                logger.info(
                    "[Decision] Contradiction detected in evidence. Routing to planner for resolution."
                )
                return Decision(
                    action="planner",
                    confidence=0.95,
                    data={
                        **decision_data,
                        "resolve_conflict": True,
                    },
                )

            # -------------------------------------------------
            # MULTI-STEP / PLANNING GOALS
            # -------------------------------------------------
            if plan or goal == "plan":
                logger.info(
                    "[Decision] Multi-step goal or plan detected. Routing to planner. goal=%s",
                    goal,
                )
                return Decision(
                    action="planner",
                    confidence=max(confidence, 0.90),
                    data=decision_data,
                )

            # -------------------------------------------------
            # EVIDENCE CHECK & LOW CONFIDENCE RECOVERY
            # -------------------------------------------------
            if len(evidence) == 0 or confidence < 0.60:
                logger.info(
                    "[Decision] Low confidence (%.2f) or empty evidence. Triggering knowledge search / web fallback.",
                    confidence,
                )
                return Decision(
                    action="knowledge_search",
                    confidence=0.60,
                    data={
                        **decision_data,
                        "web_search": True,
                        "learn_result": True,
                    },
                )

            # -------------------------------------------------
            # CONFIDENCE-BASED ROUTING TIERS
            # -------------------------------------------------
            if confidence >= 0.90:
                logger.info(
                    "[Decision] High confidence (%.2f). Executing normally with action=%s",
                    confidence,
                    action,
                )
            elif confidence >= 0.70:
                logger.info(
                    "[Decision] Moderate confidence (%.2f). Executing and preserving evidence.",
                    confidence,
                )
            else:
                logger.info(
                    "[Decision] Marginal confidence (%.2f). Requesting additional retrieval.",
                    confidence,
                )
                if self.knowledge_manager:
                    return Decision(
                        action="knowledge_search",
                        confidence=confidence,
                        data={**decision_data, "search_more": True},
                    )

            return Decision(
                action=action,
                confidence=confidence,
                data=decision_data,
            )

        # -----------------------------------------------------
        # 2. SKILL CAPABILITY FALLBACK
        # -----------------------------------------------------
        if skill_manager:
            try:
                if await skill_manager.can_handle(query, context):
                    logger.info("[Decision] SkillManager accepted request.")
                    return Decision(
                        action="skill",
                        confidence=0.90
                    )
            except Exception:
                logger.exception("[Decision] Skill capability check failed.")

        # -----------------------------------------------------
        # 3. DOCUMENT CONTEXT FALLBACK
        # -----------------------------------------------------
        document_active = bool(
            document.get("active")
            or state.get("active_document")
            or state.get("current_document")
        )

        if document_active and conversation.get("looks_like_follow_up"):
            logger.info("[Decision] Preserving active document context for unresolved follow-up.")
            return Decision(
                action="document",
                confidence=0.75,
                data={
                    "document_name": (
                        document.get("name")
                        or state.get("active_document")
                        or state.get("current_document")
                    ),
                    "contextual_fallback": True,
                },
            )

        # -----------------------------------------------------
        # 4. CONVERSATIONAL CONTINUITY FALLBACK
        # -----------------------------------------------------
        if conversation.get("looks_like_follow_up"):
            logger.info("[Decision] Falling back to conversational continuity.")
            return Decision(
                action="chat",
                confidence=0.85,
                data={"preserve_context": True}
            )

        # -----------------------------------------------------
        # 5. UNIVERSAL SAFE DEFAULT
        # -----------------------------------------------------
        logger.info("[Decision] No specialized route required. Using general conversation.")
        return Decision(
            action="chat",
            confidence=0.80
        )