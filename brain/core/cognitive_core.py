import logging
from typing import Dict, Any, Optional

from personality.response import SystemResponse
from brain.response.response_formatter import ResponseFormatter
from brain.agents.response_fusion import ResponseFusion

logger = logging.getLogger("aria")


# =============================================================
# CONFIRMATION VOCABULARY
# =============================================================

CONFIRM_WORDS = {
    "yes",
    "yes please",
    "yeah",
    "yep",
    "confirm",
    "continue",
    "proceed",
    "do it",
    "go ahead",
    "approved",
    "approve",
}

REJECT_WORDS = {
    "no",
    "nope",
    "cancel",
    "stop",
    "don't",
    "do not",
    "reject",
    "deny",
}


class CognitiveCore:
    """
    Central orchestrator of ARIA.

    Coordinates:

    - intent analysis
    - memory
    - context
    - reasoning
    - decision making
    - agents
    - skills
    - direct actions
    - planning
    - multi-step execution
    - workflow confirmation
    - workflow suspension/resumption
    """

    def __init__(
        self,
        planner,
        executor,
        skill_manager,
        action_manager=None,
        memory_router=None,
        state_manager=None,
        intent_analyzer=None,
        context_builder=None,
        decision_engine=None,
        memory_conversation_manager=None,
        reasoning_engine=None,
        knowledge_manager=None,
    ):
        self.planner = planner
        self.executor = executor
        self.skill_manager = skill_manager
        self.action_manager = action_manager
        self.memory_router = memory_router
        self.state_manager = state_manager
        self.intent_analyzer = intent_analyzer
        self.context_builder = context_builder
        self.decision_engine = decision_engine
        self.memory_conversation_manager = memory_conversation_manager
        self.reasoning_engine = reasoning_engine
        self.knowledge_manager = knowledge_manager

        self.response_formatter = ResponseFormatter()
        self.response_fusion = ResponseFusion()

    # =========================================================
    # HELPERS
    # =========================================================

    def _normalize_confirmation_text(
        self,
        query: str,
    ) -> str:
        return str(query or "").strip().lower()

    def _is_confirm(
        self,
        query: str,
    ) -> bool:
        return (
            self._normalize_confirmation_text(query)
            in CONFIRM_WORDS
        )

    def _is_reject(
        self,
        query: str,
    ) -> bool:
        return (
            self._normalize_confirmation_text(query)
            in REJECT_WORDS
        )

    def _looks_like_web_search_request(
        self,
        query: str,
    ) -> bool:
        q = str(query or "").strip().lower()

        explicit_search_phrases = (
            "search the web",
            "search web",
            "search online",
            "search the internet",
            "browse the web",
            "browse online",
            "look up online",
            "look it up online",
            "find online",
            "look up on the internet",
        )

        if any(
            phrase in q
            for phrase in explicit_search_phrases
        ):
            return True

        freshness_terms = (
            "latest",
            "current",
            "recent",
            "today",
            "today's",
            "right now",
            "newest",
            "breaking",
        )

        information_terms = (
            "news",
            "update",
            "updates",
            "development",
            "developments",
            "information",
            "announcement",
            "announcements",
            "happening",
        )

        has_freshness = any(
            term in q
            for term in freshness_terms
        )

        has_information = any(
            term in q
            for term in information_terms
        )

        return has_freshness and has_information

    def _build_confirmation_message(
        self,
        action_name: Optional[str] = None,
    ) -> str:
        if action_name:
            return (
                f"The action '{action_name}' requires your "
                "confirmation. Shall I continue?"
            )

        return (
            "This action requires your confirmation. "
            "Shall I continue?"
        )

    # =========================================================
    # WORKFLOW CONFIRMATION / RESUMPTION
    # =========================================================

    async def _handle_pending_workflow(
        self,
        *,
        query: str,
        session_id: str,
        base_context: Optional[Dict[str, Any]],
        state: Dict[str, Any],
    ) -> Optional[SystemResponse]:
        """
        Handle confirmation for a suspended multi-step workflow.

        Returns None when the current message is not resolving
        the pending workflow confirmation.
        """

        if not self.state_manager:
            return None

        if not state.get(
            "pending_workflow_confirmation"
        ):
            return None

        pending_plan = (
            self.state_manager.get_pending_workflow(
                session_id
            )
        )

        pending_task_id = (
            self.state_manager.get_pending_workflow_task_id(
                session_id
            )
        )

        # -----------------------------------------------------
        # Invalid / stale workflow state
        # -----------------------------------------------------

        if (
            pending_plan is None
            or not pending_task_id
        ):
            logger.warning(
                "[CognitiveCore] Invalid pending workflow state."
            )

            self.state_manager.clear_workflow(
                session_id
            )

            return SystemResponse(
                success=False,
                confidence=1.0,
                source="workflow_confirmation",
                error=(
                    "The pending workflow is no longer available."
                ),
            )

        # -----------------------------------------------------
        # USER REJECTED
        # -----------------------------------------------------

        if self._is_reject(query):

            logger.info(
                "[CognitiveCore] User cancelled workflow "
                "at task %s.",
                pending_task_id,
            )

            self.state_manager.cancel_workflow(
                session_id
            )

            return SystemResponse(
                success=True,
                confidence=1.0,
                source="workflow_confirmation",
                data={
                    "message": "Workflow cancelled."
                },
            )

        # -----------------------------------------------------
        # Not confirmation/rejection.
        #
        # Keep workflow suspended.
        # -----------------------------------------------------

        if not self._is_confirm(query):

            return SystemResponse(
                success=True,
                confidence=1.0,
                source="workflow_confirmation",
                data={
                    "confirmation_required": True,
                    "message": (
                        "The current workflow is waiting for "
                        "your confirmation. Shall I continue?"
                    ),
                },
            )

        # -----------------------------------------------------
        # USER CONFIRMED
        # -----------------------------------------------------

        logger.info(
            "[CognitiveCore] Resuming workflow at task %s.",
            pending_task_id,
        )

        resume_state = (
            self.state_manager.get_workflow_progress(
                session_id
            )
        )

        self.state_manager.mark_workflow_resumed(
            session_id
        )

        # Build enough context for the Executor.
        ctx = dict(
            base_context or {}
        )

        ctx["state"] = (
            self.state_manager.get_state(
                session_id
            )
        )

        try:

            exec_result = (
                await self.executor.execute_plan(
                    pending_plan,
                    ctx,
                    resume_state=resume_state,
                    confirmed_task_id=pending_task_id,
                )
            )

        except Exception as exc:

            logger.exception(
                "[CognitiveCore] Workflow resume failed."
            )

            self.state_manager.mark_workflow_failed(
                session_id,
                error=str(exc),
            )

            return SystemResponse(
                success=False,
                confidence=1.0,
                source="planner_executor",
                error=str(exc),
            )

        return self._process_workflow_result(
            session_id=session_id,
            plan=pending_plan,
            exec_result=exec_result,
        )

    # =========================================================
    # WORKFLOW RESULT PROCESSING
    # =========================================================

    def _process_workflow_result(
        self,
        *,
        session_id: str,
        plan,
        exec_result: Dict[str, Any],
    ) -> SystemResponse:
        """
        Convert Executor workflow state into SystemResponse and
        persist pause/resume information when necessary.
        """

        if not isinstance(
            exec_result,
            dict,
        ):
            if self.state_manager:
                self.state_manager.mark_workflow_failed(
                    session_id,
                    error="Executor returned an invalid result.",
                )

            return SystemResponse(
                success=False,
                confidence=getattr(
                    plan,
                    "confidence",
                    0.0,
                ),
                source="planner_executor",
                error="Executor returned an invalid result.",
            )

        task_outputs = (
            exec_result.get(
                "task_outputs",
                {},
            )
            or {}
        )

        workflow_results = (
            exec_result.get(
                "workflow_results",
                {},
            )
            or {}
        )

        completed = (
            exec_result.get(
                "completed",
                [],
            )
            or []
        )

        failed = (
            exec_result.get(
                "failed",
                [],
            )
            or []
        )

        skipped = (
            exec_result.get(
                "skipped",
                [],
            )
            or []
        )

        paused = bool(
            exec_result.get(
                "paused",
                False,
            )
        )

        requires_confirmation = bool(
            exec_result.get(
                "requires_confirmation",
                False,
            )
        )

        pending_task_id = (
            exec_result.get(
                "pending_task_id"
            )
        )

        pending_action_name = (
            exec_result.get(
                "pending_action_name"
            )
        )

        # =====================================================
        # WORKFLOW PAUSED FOR CONFIRMATION
        # =====================================================

        if (
            paused
            and requires_confirmation
        ):

            if not self.state_manager:

                return SystemResponse(
                    success=False,
                    confidence=getattr(
                        plan,
                        "confidence",
                        0.0,
                    ),
                    source="workflow_confirmation",
                    error=(
                        "State manager is unavailable; "
                        "workflow cannot be suspended safely."
                    ),
                )

            logger.info(
                "[CognitiveCore] Persisting suspended workflow "
                "at task %s (%s).",
                pending_task_id,
                pending_action_name,
            )

            self.state_manager.set_pending_workflow(
                session_id=session_id,
                plan=plan,
                task_id=pending_task_id,
                task_outputs=task_outputs,
                completed_tasks=completed,
                failed_tasks=failed,
                skipped_tasks=skipped,
            )

            return SystemResponse(
                success=True,
                confidence=getattr(
                    plan,
                    "confidence",
                    0.95,
                ),
                source="workflow_confirmation",
                data={
                    "confirmation_required": True,
                    "workflow_paused": True,
                    "task_id": pending_task_id,
                    "action_name": pending_action_name,
                    "message": (
                        self._build_confirmation_message(
                            pending_action_name
                        )
                    ),
                },
            )

        # =====================================================
        # WORKFLOW FAILED
        # =====================================================

        success = bool(
            exec_result.get(
                "success",
                False,
            )
        )

        if not success:

            error = (
                "Orchestration tasks encountered failures."
            )

            if failed:
                error = (
                    "Workflow failed while executing task(s): "
                    + ", ".join(
                        str(item)
                        for item in failed
                    )
                )

            elif skipped:
                error = (
                    "Workflow could not complete because "
                    "task(s) were skipped: "
                    + ", ".join(
                        str(item)
                        for item in skipped
                    )
                )

            if self.state_manager:

                self.state_manager.mark_workflow_failed(
                    session_id,
                    error=error,
                )

            logger.warning(
                "[CognitiveCore] Workflow failed. "
                "failed=%s skipped=%s",
                failed,
                skipped,
            )

            return SystemResponse(
                success=False,
                confidence=getattr(
                    plan,
                    "confidence",
                    0.5,
                ),
                source="planner_executor",
                data={
                    "task_outputs": task_outputs,
                    "workflow_results": workflow_results,
                },
                error=error,
            )

        # =====================================================
        # WORKFLOW COMPLETED
        # =====================================================

        if self.state_manager:

            self.state_manager.mark_workflow_completed(
                session_id
            )

            self.state_manager.update_state(
                session_id,
                last_action="planner_executor",
                last_success=True,
            )

        logger.info(
            "[CognitiveCore] Workflow completed successfully."
        )

        # =====================================================
        # EXTRACT USER-FACING OUTPUT FROM FINAL TASK
        # =====================================================

        final_message = None

        for task in reversed(plan.tasks):

            output = task_outputs.get(task.id)

            if not isinstance(output, dict):
                continue

            for field in (
                "response",
                "content",
                "message",
                "answer",
                "summary",
            ):

                value = output.get(field)

                if isinstance(value, str) and value.strip():
                    final_message = value.strip()
                    break

            if final_message:
                break

        response_data = {
            "task_outputs": task_outputs,
            "workflow_results": workflow_results,
        }

        if final_message:
            response_data["message"] = final_message
            response_data["response"] = final_message

        return SystemResponse(
            success=True,
            confidence=getattr(
                plan,
                "confidence",
                0.95,
            ),
            source="planner_executor",
            data=response_data,
        )

    # =========================================================
    # MAIN PROCESS
    # =========================================================

    async def process(
        self,
        query: str,
        session_id: str = "",
        user_id: str = "",
        base_context: Optional[Dict[str, Any]] = None,
    ) -> SystemResponse:
        """
        Main cognitive orchestration pipeline.

        CognitiveCore should coordinate ARIA's subsystems rather
        than trying to understand every possible user command
        through hard-coded keyword rules.

        Pipeline:

            State
              ↓
            Pending confirmations
              ↓
            Memory retrieval
              ↓
            Context construction
              ↓
            Intent hint
              ↓
            Reasoning
              ↓
            Decision
              ↓
            Planner when necessary
              ↓
            Executor
              ↓
            Response
        """

        try:

            # =================================================
            # 1. LOAD STATE
            # =================================================

            state: Dict[str, Any] = {}

            if self.state_manager:
                state = (
                    self.state_manager.get_state(session_id)
                    or {}
                )

            # =================================================
            # 2. RESUME / CANCEL PENDING WORKFLOW
            # =================================================

            workflow_response = (
                await self._handle_pending_workflow(
                    query=query,
                    session_id=session_id,
                    base_context=base_context,
                    state=state,
                )
            )

            if workflow_response is not None:
                return workflow_response

            # =================================================
            # 3. HANDLE PENDING DIRECT ACTION
            # =================================================

            if (
                self.state_manager
                and state.get("pending_action_confirmation")
            ):

                normalized_query = (
                    self._normalize_confirmation_text(query)
                )

                # ---------------------------------------------
                # CONFIRM
                # ---------------------------------------------

                if self._is_confirm(normalized_query):

                    action_name = state.get(
                        "pending_action_name"
                    )

                    action_params = (
                        state.get(
                            "pending_action_params",
                            {},
                        )
                        or {}
                    )

                    # Clear before execution to prevent replay.
                    self.state_manager.clear_pending_action(
                        session_id
                    )

                    if (
                        not self.action_manager
                        or not action_name
                        or action_name
                        not in self.action_manager.actions
                    ):
                        return SystemResponse(
                            success=False,
                            confidence=1.0,
                            source="action_confirmation",
                            error=(
                                "The pending action is no "
                                "longer available."
                            ),
                        )

                    logger.info(
                        "[CognitiveCore] Executing confirmed "
                        "action: %s",
                        action_name,
                    )

                    action_result = (
                        await self.action_manager.execute_action(
                            action_name=action_name,
                            params=action_params,
                            confirmed=True,
                        )
                    )

                    response_data = {
                        "action_name": action_name,
                        "result": action_result.data,
                    }

                    # Preserve readable file contents.
                    if (
                        action_result.success
                        and action_name == "file_action"
                        and action_params.get("mode") == "read"
                    ):
                        content = (
                            action_result.data or {}
                        ).get("content")

                        if content:
                            response_data["message"] = content

                    return SystemResponse(
                        success=action_result.success,
                        confidence=1.0,
                        source="action_manager",
                        data=response_data,
                        error=action_result.error,
                    )

                # ---------------------------------------------
                # REJECT
                # ---------------------------------------------

                if self._is_reject(normalized_query):

                    action_name = state.get(
                        "pending_action_name"
                    )

                    self.state_manager.clear_pending_action(
                        session_id
                    )

                    logger.info(
                        "[CognitiveCore] User cancelled "
                        "action: %s",
                        action_name,
                    )

                    return SystemResponse(
                        success=True,
                        confidence=1.0,
                        source="action_confirmation",
                        data={
                            "message": "Action cancelled."
                        },
                    )

                # User said something unrelated while a direct
                # action is waiting for confirmation.
                return SystemResponse(
                    success=True,
                    confidence=1.0,
                    source="action_confirmation",
                    data={
                        "confirmation_required": True,
                        "message": (
                            "The pending action is waiting for "
                            "your confirmation. Shall I continue?"
                        ),
                    },
                )

            # =================================================
            # 4. RETRIEVE RELEVANT MEMORY
            # =================================================

            memories = []

            if self.memory_router:

                try:
                    memories = (
                        await self.memory_router
                        .get_relevant_memories(query)
                    ) or []

                except Exception:
                    logger.exception(
                        "[CognitiveCore] Memory retrieval failed."
                    )

            # =================================================
            # 5. BUILD COMPLETE CONTEXT
            # =================================================

            if self.context_builder:

                ctx = await self.context_builder.build(
                    query=query,
                    session_id=session_id,
                    user_id=user_id,
                    base_context=base_context,
                    memory=memories,
                    state=state,
                )

            else:

                ctx = dict(base_context or {})

                ctx["query"] = query
                ctx["session_id"] = session_id
                ctx["user_id"] = user_id
                ctx["state"] = state
                ctx["memory"] = memories

            # Guarantee essential context exists even if the
            # ContextBuilder omitted one of these fields.

            ctx.setdefault("query", query)
            ctx.setdefault("session_id", session_id)
            ctx.setdefault("user_id", user_id)
            ctx.setdefault("state", state)
            ctx.setdefault("memory", memories)

            # =================================================
            # 6. ATTACH REGISTERED CAPABILITIES
            # =================================================

            app_state = None

            if base_context:
                app_state = base_context.get("app_state")

            document_ai = None
            document_repository = None

            if app_state:

                try:
                    if app_state.registry.has(
                        "document_intelligence"
                    ):
                        document_ai = app_state.registry.get(
                            "document_intelligence"
                        )
                except Exception:
                    logger.exception(
                        "[CognitiveCore] Could not obtain "
                        "document intelligence."
                    )

                try:
                    if app_state.registry.has(
                        "document_repository"
                    ):
                        document_repository = (
                            app_state.registry.get(
                                "document_repository"
                            )
                        )
                except Exception:
                    logger.exception(
                        "[CognitiveCore] Could not obtain "
                        "document repository."
                    )

            ctx["document_intelligence"] = document_ai
            ctx["document_repository"] = document_repository

            # Expose managers as capabilities to later reasoning
            # and planning layers.

            ctx["capabilities"] = {
                "memory": self.memory_router is not None,
                "documents": document_ai is not None,
                "document_repository":
                    document_repository is not None,
                "skills": self.skill_manager is not None,
                "actions": self.action_manager is not None,
                "planner": self.planner is not None,
                "executor": self.executor is not None,
            }

            # =================================================
            # 7. SAVE CURRENT QUERY
            # =================================================

            if self.state_manager:
                self.state_manager.update_state(
                    session_id,
                    last_query=query,
                )

            # =================================================
            # 8. INTENT ANALYSIS
            #
            # Intent is now a HINT.
            # It must not control the whole architecture.
            # =================================================

            intent = None

            if self.intent_analyzer:

                try:
                    intent = (
                        await self.intent_analyzer.analyze(query)
                    )

                    ctx["intent"] = intent

                except Exception:
                    logger.exception(
                        "[CognitiveCore] Intent analysis failed."
                    )

            # =================================================
            # 9. EXPLICIT MEMORY MANAGEMENT
            #
            # Memory write/delete operations remain deterministic
            # because they change persistent user data.
            # =================================================

            if (
                intent
                and intent.name in (
                    "memory_store",
                    "memory_update",
                    "memory_delete",
                )
                and self.memory_conversation_manager
            ):

                logger.info(
                    "[CognitiveCore] Explicit memory operation: %s",
                    intent.name,
                )

                reply = (
                    await self.memory_conversation_manager.handle(
                        query=query,
                        context=ctx,
                    )
                )

                return SystemResponse(
                    success=True,
                    confidence=getattr(
                        intent,
                        "confidence",
                        1.0,
                    ),
                    source="memory_conversation",
                    data={
                        "message": reply,
                    },
                )

            # =================================================
            # 10. NATURAL MEMORY LEARNING
            #
            # Learn useful persistent facts without turning the
            # entire message into a memory-only interaction.
            # =================================================

            if self.memory_router:

                try:

                    memory_result = (
                        await self.memory_router
                        .process_and_store(query)
                    )

                    if (
                        memory_result
                        and memory_result.get("success")
                    ):

                        logger.info(
                            "[CognitiveCore] Natural memory "
                            "learning: key=%s action=%s",
                            memory_result.get("key"),
                            memory_result.get("action"),
                        )

                        # Refresh retrieved context so reasoning
                        # sees the newest value immediately.

                        try:

                            refreshed = (
                                await self.memory_router
                                .get_relevant_memories(query)
                            )

                            if refreshed is not None:
                                memories = refreshed
                                ctx["memory"] = refreshed

                        except Exception:
                            logger.exception(
                                "[CognitiveCore] Memory refresh "
                                "failed."
                            )

                except Exception:
                    logger.exception(
                        "[CognitiveCore] Natural memory "
                        "learning failed."
                    )

            # =================================================
            # 11. REASONING
            #
            # This becomes the semantic understanding layer.
            # =================================================

            reasoning = None

            if self.reasoning_engine:

                try:

                    reasoning = (
                        await self.reasoning_engine.reason(ctx)
                    )

                    ctx["reasoning"] = reasoning

                    logger.info(
                        "[CognitiveCore] Reasoning completed: "
                        "action=%s confidence=%s",
                        getattr(
                            reasoning,
                            "primary_action",
                            None,
                        ),
                        getattr(
                            reasoning,
                            "confidence",
                            None,
                        ),
                    )

                except Exception:

                    logger.exception(
                        "[CognitiveCore] Reasoning failed."
                    )

            # =================================================
            # 12. DECISION
            #
            # DecisionEngine decides which CAPABILITY is suitable.
            # CognitiveCore does not inspect Monday, PDF, news,
            # filenames, conjunctions, etc.
            # =================================================

            decision = None

            if self.decision_engine:

                try:

                    decision = (
                        await self.decision_engine.decide(
                            context=ctx,
                            skill_manager=self.skill_manager,
                            planner=self.planner,
                        )
                    )

                    ctx["decision"] = decision

                except Exception:

                    logger.exception(
                        "[CognitiveCore] Decision engine failed."
                    )

            selected_action = getattr(
                decision,
                "action",
                None,
            )

            logger.info(
                "[CognitiveCore] Selected capability: %s",
                selected_action,
            )

            # =================================================
            # 13. SAFE DETERMINISTIC CAPABILITIES
            # =================================================

            # -------------------------------------------------
            # MEMORY RECALL
            # -------------------------------------------------

            if (
                selected_action == "memory_conversation"
                and self.memory_conversation_manager
            ):

                reply = (
                    await self.memory_conversation_manager.handle(
                        query=query,
                        context=ctx,
                    )
                )

                if reply and reply.strip():

                    return SystemResponse(
                        success=True,
                        confidence=getattr(
                            decision,
                            "confidence",
                            0.9,
                        ),
                        source="memory",
                        data={
                            "message": reply,
                        },
                    )

                # If memory cannot answer confidently, don't
                # terminate cognition. Let Planner reason using
                # other available sources.

                logger.info(
                    "[CognitiveCore] Memory could not answer; "
                    "falling through to planner."
                )

            # -------------------------------------------------
            # DOCUMENT
            # -------------------------------------------------

            if selected_action == "document":

                if document_ai:

                    answer = (
                        await document_ai.answer_question(
                            session_id=session_id,
                            question=query,
                            state=ctx.get("state"),
                        )
                    )

                    if answer:

                        if self.state_manager:
                            self.state_manager.update_state(
                                session_id,
                                last_document_question=query,
                                last_document_answer=answer,
                            )

                        return SystemResponse(
                            success=True,
                            confidence=getattr(
                                decision,
                                "confidence",
                                0.9,
                            ),
                            source="document",
                            data={
                                "response": answer,
                            },
                        )

                logger.info(
                    "[CognitiveCore] Document capability could "
                    "not answer; falling through to planner."
                )

            # -------------------------------------------------
            # SKILL
            # -------------------------------------------------

            if selected_action in ("skill", "chat"):

                if (
                    self.skill_manager
                    and hasattr(
                        self.skill_manager,
                        "route_and_execute",
                    )
                ):

                    skill_result = (
                        await self.skill_manager
                        .route_and_execute(
                            query,
                            ctx,
                        )
                    )

                    if (
                        skill_result
                        and skill_result.success
                    ):

                        return SystemResponse(
                            success=True,
                            confidence=getattr(
                                skill_result,
                                "confidence",
                                0.9,
                            ),
                            source=getattr(
                                skill_result,
                                "source",
                                "skill",
                            ),
                            data=skill_result.data,
                        )

            # -------------------------------------------------
            # DIRECT ACTION
            #
            # Only execute directly when reasoning has produced
            # exactly one clear registered action.
            # Otherwise Planner handles it.
            # -------------------------------------------------

            if (
                selected_action == "action"
                and self.action_manager
            ):

                action_name = getattr(
                    reasoning,
                    "action_name",
                    None,
                )

                action_params = getattr(
                    reasoning,
                    "action_params",
                    {},
                ) or {}

                if (
                    action_name
                    and action_name
                    in self.action_manager.actions
                ):

                    action_instance = (
                        self.action_manager.actions[
                            action_name
                        ]
                    )

                    if (
                        action_instance.permission_level
                        == "confirm"
                    ):

                        if not self.state_manager:

                            return SystemResponse(
                                success=False,
                                confidence=1.0,
                                source="action_confirmation",
                                error=(
                                    "State manager is unavailable."
                                ),
                            )

                        self.state_manager.set_pending_action(
                            session_id=session_id,
                            action_name=action_name,
                            action_params=action_params,
                        )

                        return SystemResponse(
                            success=True,
                            confidence=getattr(
                                decision,
                                "confidence",
                                0.9,
                            ),
                            source="action_confirmation",
                            data={
                                "confirmation_required": True,
                                "action_name": action_name,
                                "message": (
                                    self._build_confirmation_message(
                                        action_name
                                    )
                                ),
                            },
                        )

                    result = (
                        await self.action_manager.execute_action(
                            action_name=action_name,
                            params=action_params,
                        )
                    )

                    if result.success:

                        return SystemResponse(
                            success=True,
                            confidence=getattr(
                                decision,
                                "confidence",
                                0.9,
                            ),
                            source="action_manager",
                            data={
                                "action_name": action_name,
                                "result": result.data,
                            },
                        )

                    return SystemResponse(
                        success=False,
                        confidence=getattr(
                            decision,
                            "confidence",
                            0.5,
                        ),
                        source="action_manager",
                        error=result.error,
                    )

                # Ambiguous action → Planner.
                logger.info(
                    "[CognitiveCore] Direct action was not "
                    "sufficiently specified. Using planner."
                )

            # =================================================
            # 14. PLANNER
            #
            # Everything that wasn't confidently solved by one
            # capability reaches the Planner.
            #
            # This is what enables:
            #
            #   document → memory → web → action
            #
            # in ONE user request.
            # =================================================

            plan = None

            if (
                self.planner
                and hasattr(
                    self.planner,
                    "create_plan",
                )
            ):

                plan = (
                    await self.planner.create_plan(
                        query,
                        ctx,
                    )
                )

            elif (
                self.planner
                and hasattr(
                    self.planner,
                    "plan",
                )
            ):

                possible_plan = (
                    self.planner.plan(
                        query,
                        ctx,
                    )
                )

                # Support both synchronous and asynchronous
                # planner implementations.

                if hasattr(
                    possible_plan,
                    "__await__",
                ):
                    plan = await possible_plan
                else:
                    plan = possible_plan

            # =================================================
            # 15. CONVERSATIONAL FALLBACK
            # =================================================

            if (
                not plan
                or not getattr(
                    plan,
                    "tasks",
                    None,
                )
            ):

                # If SkillManager can provide normal conversation,
                # give it one final opportunity.

                if (
                    self.skill_manager
                    and hasattr(
                        self.skill_manager,
                        "route_and_execute",
                    )
                ):

                    try:

                        chat_result = (
                            await self.skill_manager
                            .route_and_execute(
                                query,
                                ctx,
                            )
                        )

                        if (
                            chat_result
                            and chat_result.success
                        ):

                            return SystemResponse(
                                success=True,
                                confidence=getattr(
                                    chat_result,
                                    "confidence",
                                    0.8,
                                ),
                                source=getattr(
                                    chat_result,
                                    "source",
                                    "chat",
                                ),
                                data=chat_result.data,
                            )

                    except Exception:

                        logger.exception(
                            "[CognitiveCore] Conversational "
                            "fallback failed."
                        )

                return SystemResponse(
                    success=True,
                    confidence=getattr(
                        plan,
                        "confidence",
                        0.5,
                    ),
                    source="planner_conversational",
                    data={
                        "intent": "conversational",
                        "query": query,
                    },
                )

            logger.info(
                "[CognitiveCore] Executing cognitive plan "
                "with %d task(s).",
                len(plan.tasks),
            )

            # =================================================
            # 16. EXECUTOR
            # =================================================

            if (
                not self.executor
                or not hasattr(
                    self.executor,
                    "execute_plan",
                )
            ):

                return SystemResponse(
                    success=False,
                    confidence=getattr(
                        plan,
                        "confidence",
                        0.0,
                    ),
                    source="planner_executor",
                    error="Executor is unavailable.",
                )

            exec_result = (
                await self.executor.execute_plan(
                    plan,
                    ctx,
                )
            )

            # =================================================
            # 17. PROCESS WORKFLOW RESULT
            # =================================================

            return self._process_workflow_result(
                session_id=session_id,
                plan=plan,
                exec_result=exec_result,
            )

        # =====================================================
        # GLOBAL ERROR HANDLER
        # =====================================================

        except Exception as exc:

            logger.exception(
                "[CognitiveCore ERROR] Processing failed: %s",
                exc,
            )

            return SystemResponse(
                success=False,
                confidence=0.0,
                source="cognitive_core",
                error=str(exc),
            )
