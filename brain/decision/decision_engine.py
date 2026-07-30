import logging
from typing import Any, Dict, Optional, List

from brain.models.decision import Decision

logger = logging.getLogger("aria")


class DecisionEngine:
    """
    Chooses how ARIA should respond to a user request based on unified context.

    It DOES NOT execute anything.
    It only decides what should happen next.
    """

    async def decide(
        self,
        context: Dict[str, Any],
        skill_manager=None,
        planner=None
    ) -> Decision:
        """
        Convert ARIA's reasoning result into the final execution route.

        The DecisionEngine does not try to understand the user's
        language again. ContextBuilder and ReasoningEngine have already
        done that work.

        Its responsibility is to choose the safest and most appropriate
        execution path from the available reasoning and context.
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

            action = getattr(
                reasoning,
                "primary_action",
                None
            )

            confidence = getattr(
                reasoning,
                "confidence",
                0.80
            )

            secondary_actions = getattr(
                reasoning,
                "secondary_actions",
                []
            )

            metadata = getattr(
                reasoning,
                "metadata",
                {}
            ) or {}

            action_name = getattr(
                reasoning,
                "action_name",
                None
            )

            action_params = getattr(
                reasoning,
                "action_params",
                {}
            ) or {}

            if action:

                logger.info(
                    "[Decision] Reasoning selected action=%s "
                    "confidence=%.2f goal=%s",
                    action,
                    confidence,
                    metadata.get("goal")
                )

                return Decision(
                    action=action,
                    confidence=confidence,
                    secondary_actions=secondary_actions,
                    data=metadata,
                    action_name=action_name,
                    action_params=action_params
                )

        # -----------------------------------------------------
        # 2. SKILL CAPABILITY FALLBACK
        # -----------------------------------------------------
        #
        # This is used only when reasoning was unavailable.
        # It allows a registered skill to claim a request without
        # requiring DecisionEngine to understand that request itself.
        # -----------------------------------------------------

        if skill_manager:

            try:

                if await skill_manager.can_handle(
                    query,
                    context
                ):

                    logger.info(
                        "[Decision] SkillManager accepted request."
                    )

                    return Decision(
                        action="skill",
                        confidence=0.90
                    )

            except Exception:

                logger.exception(
                    "[Decision] Skill capability check failed."
                )

        # -----------------------------------------------------
        # 3. DOCUMENT CONTEXT FALLBACK
        # -----------------------------------------------------
        #
        # Do not inspect document keywords here.
        # If a document is genuinely active and reasoning was somehow
        # unavailable, preserve that context.
        # -----------------------------------------------------

        document_active = bool(
            document.get("active")
            or state.get("active_document")
            or state.get("current_document")
        )

        if document_active:

            logger.info(
                "[Decision] Falling back to active document context."
            )

            return Decision(
                action="document",
                confidence=0.85,
                data={
                    "document_name": (
                        document.get("name")
                        or state.get("active_document")
                        or state.get("current_document")
                    )
                }
            )

        # -----------------------------------------------------
        # 4. CONVERSATIONAL CONTINUITY FALLBACK
        # -----------------------------------------------------

        if conversation.get("looks_like_follow_up"):

            logger.info(
                "[Decision] Falling back to conversational continuity."
            )

            return Decision(
                action="chat",
                confidence=0.85,
                data={
                    "preserve_context": True
                }
            )

        # -----------------------------------------------------
        # 5. UNIVERSAL SAFE DEFAULT
        # -----------------------------------------------------
        #
        # Unknown language should remain conversational instead of
        # failing merely because no keyword matched.
        # -----------------------------------------------------

        logger.info(
            "[Decision] No specialized route required. "
            "Using general conversation."
        )

        return Decision(
            action="chat",
            confidence=0.80
        )
