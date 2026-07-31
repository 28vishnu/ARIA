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

        try:

            # =================================================
            # 1. STATE
            # =================================================

            state = {}

            if self.state_manager:
                state = self.state_manager.get_state(
                    session_id
                )

            # =================================================
            # 2. PENDING MULTI-STEP WORKFLOW
            #
            # IMPORTANT:
            # Workflow confirmation has priority over ordinary
            # single-action confirmation.
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
            # 3. PENDING DIRECT ACTION
            # =================================================

            if (
                self.state_manager
                and state.get(
                    "pending_action_confirmation"
                )
            ):

                normalized_query = (
                    self._normalize_confirmation_text(
                        query
                    )
                )

                # ---------------------------------------------
                # CONFIRM DIRECT ACTION
                # ---------------------------------------------

                if normalized_query in CONFIRM_WORDS:

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

                    # Clear first to prevent replay.
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
                        "[CognitiveCore] Confirmed direct "
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

                    # File reads should expose actual contents.
                    if (
                        action_result.success
                        and action_name == "file_action"
                        and action_params.get("mode")
                        == "read"
                    ):

                        content = (
                            action_result.data or {}
                        ).get(
                            "content",
                            "",
                        )

                        response_data[
                            "message"
                        ] = content

                    return SystemResponse(
                        success=action_result.success,
                        confidence=1.0,
                        source="action_manager",
                        data=response_data,
                        error=action_result.error,
                    )

                # ---------------------------------------------
                # REJECT DIRECT ACTION
                # ---------------------------------------------

                if normalized_query in REJECT_WORDS:

                    pending_action_name = state.get(
                        "pending_action_name"
                    )

                    self.state_manager.clear_pending_action(
                        session_id
                    )

                    logger.info(
                        "[CognitiveCore] User cancelled "
                        "pending action: %s",
                        pending_action_name,
                    )

                    return SystemResponse(
                        success=True,
                        confidence=1.0,
                        source="action_confirmation",
                        data={
                            "message": "Action cancelled."
                        },
                    )

            # =================================================
            # 4. MEMORY RETRIEVAL
            # =================================================

            memories = []

            if self.memory_router:

                try:

                    memories = (
                        await self.memory_router
                        .get_relevant_memories(
                            query
                        )
                    )

                except Exception:

                    logger.exception(
                        "[CognitiveCore] Memory retrieval "
                        "failed."
                    )

            # =================================================
            # 6. CONTEXT
            # =================================================

            if self.context_builder:

                ctx = (
                    await self.context_builder.build(
                        query=query,
                        session_id=session_id,
                        user_id=user_id,
                        base_context=base_context,
                        memory=memories,
                        state=state,
                    )
                )

            else:

                ctx = dict(
                    base_context or {}
                )

                ctx["state"] = state
                ctx["memory"] = memories

            # -------------------------------------------------
            # Document Intelligence
            # -------------------------------------------------

            document_ai = None

            if base_context:

                app_state = base_context.get(
                    "app_state"
                )

                if app_state:

                    try:
                        document_ai = (
                            app_state.registry.get(
                                "document_intelligence"
                            )
                        )
                    except Exception:
                        document_ai = None

            ctx[
                "document_intelligence"
            ] = document_ai

            # -------------------------------------------------
            # Last query
            # -------------------------------------------------

            if self.state_manager:

                self.state_manager.update_state(
                    session_id,
                    last_query=query,
                )

            # =================================================
            # 7. INTENT
            # =================================================

            intent = None

            if self.intent_analyzer:

                intent = (
                    await self.intent_analyzer.analyze(
                        query
                    )
                )

                ctx["intent"] = intent

                # =============================================
                # EXPLICIT MEMORY STORE / UPDATE FAST PATH
                # =============================================

                if (
                    intent
                    and intent.name in (
                        "memory_store",
                        "memory_update",
                    )
                    and self.memory_conversation_manager
                ):

                    logger.info(
                        "[CognitiveCore] Memory write fast-path "
                        "activated: %s",
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
                        confidence=intent.confidence,
                        data={
                            "message": reply
                        },
                        source="memory_conversation",
                    )

                # =============================================
                # NATURAL MEMORY LEARNING
                # =============================================

                if (
                    self.memory_router
                    and intent
                    and intent.name not in (
                        "memory_delete",
                        "memory_store",
                        "memory_update",
                    )
                ):
                    try:
                        memory_result = (
                            await self.memory_router.process_and_store(
                                query
                            )
                        )

                        if (
                            memory_result
                            and memory_result.get("success")
                        ):
                            # Refresh memory context immediately after learning/updating.
                            # The memories retrieved earlier may contain the old value.
                            try:
                                refreshed_memories = (
                                    await self.memory_router.get_relevant_memories(query)
                                )

                                if refreshed_memories:
                                    memories = refreshed_memories
                                    ctx["memory"] = refreshed_memories

                                    logger.info(
                                        "[CognitiveCore] Memory context refreshed after learning."
                                    )

                            except Exception:
                                logger.exception(
                                    "[CognitiveCore] Failed to refresh memory context after learning."
                                )

                            logger.info(
                                "[CognitiveCore] Natural memory learned: "
                                "key=%s action=%s",
                                memory_result.get("key"),
                                memory_result.get("action"),
                            )

                            key = str(
                                memory_result.get("key") or ""
                            ).strip()

                            value = str(
                                memory_result.get("value") or ""
                            ).strip()

                            if key and value:
                                readable_key = (
                                    key
                                    .replace("favorite_", "")
                                    .replace("favourite_", "")
                                    .replace("_", " ")
                                    .strip()
                                )

                                action = str(
                                    memory_result.get(
                                        "action",
                                        "stored",
                                    )
                                ).lower()

                                if action == "update":
                                    message = (
                                        f"Updated, Sir. I'll remember that "
                                        f"your {readable_key} is {value}."
                                    )
                                else:
                                    message = (
                                        f"Understood, Sir. I'll remember that "
                                        f"your {readable_key} is {value}."
                                    )

                                return SystemResponse(
                                    success=True,
                                    confidence=1.0,
                                    data={
                                        "message": message
                                    },
                                    source="memory_learning",
                                )

                    except Exception:
                        logger.exception(
                            "[CognitiveCore] Natural memory "
                            "learning failed."
                        )

            # =================================================
            # 8. FAST PATHS
            # =================================================

            if intent:

                # =============================================
                # FILESYSTEM / ACTION WORKFLOW GUARD
                # =============================================

                query_lower = query.lower()

                filesystem_extensions = (
                    ".txt",
                    ".json",
                    ".csv",
                    ".log",
                    ".md",
                    ".yaml",
                    ".yml",
                )

                filesystem_verbs = (
                    "write ",
                    "read ",
                    "append ",
                    "rename ",
                    "move ",
                    "copy ",
                    "create ",
                )

                action_chain_terms = (
                    " then ",
                    " and send ",
                    " and notify ",
                    " as a notification",
                )

                looks_like_filesystem_request = (
                    any(
                        extension in query_lower
                        for extension in filesystem_extensions
                    )
                    and any(
                        verb in query_lower
                        for verb in filesystem_verbs
                    )
                )

                looks_like_filesystem_workflow = (
                    looks_like_filesystem_request
                    and any(
                        term in query_lower
                        for term in action_chain_terms
                    )
                )

                # =============================================
                # DOCUMENT COMMAND DISAMBIGUATION
                #
                # Prevent questions such as:
                # "Summarize this document"
                # "Explain this PDF"
                # "What does this document say?"
                #
                # from being mistaken for requests to SEND the file.
                # =============================================

                document_analysis_terms = (
                    "summarize",
                    "summarise",
                    "summary",
                    "explain",
                    "analyze",
                    "analyse",
                    "what does",
                    "what is in",
                    "what's in",
                    "tell me about",
                    "important information",
                    "important points",
                    "key points",
                    "briefly",
                    "according to",
                )

                document_send_terms = (
                    "send me",
                    "send the",
                    "send this",
                    "send document",
                    "send the document",
                    "send pdf",
                    "send the pdf",
                    "give me the document",
                    "give me the file",
                    "give me this file",
                    "forward the document",
                    "forward this",
                    "share the document",
                    "share this document",
                    "download the document",
                    "download the pdf",
                )

                is_document_analysis_request = any(
                    term in query_lower
                    for term in document_analysis_terms
                )

                is_explicit_document_send_request = any(
                    term in query_lower
                    for term in document_send_terms
                )

                # Correct an intent-analyzer mistake before entering
                # the document fast path.
                if (
                    intent.name == "document_retrieve"
                    and is_document_analysis_request
                    and not is_explicit_document_send_request
                ):
                    logger.info(
                        "[CognitiveCore] Correcting document_retrieve "
                        "to document_query for analysis request."
                    )

                    intent.name = "document_query"

                # =============================================
                # DOCUMENT FAST PATHS
                # =============================================

                if (
                    not looks_like_filesystem_request
                    and intent.name in (
                        "document_retrieve",
                        "document_list",
                        "document_query",
                        "delete_document",
                        "delete_all_documents",
                    )
                ):

                    logger.info(
                        "[CognitiveCore] Document fast-path "
                        "activated: %s",
                        intent.name,
                    )

                    document_repository = None

                    document_ai = ctx.get(
                        "document_intelligence"
                    )

                    if base_context:

                        app_state = base_context.get(
                            "app_state"
                        )

                        if (
                            app_state
                            and app_state.registry.has(
                                "document_repository"
                            )
                        ):

                            document_repository = (
                                app_state.registry.get(
                                    "document_repository"
                                )
                            )

                    # -----------------------------------------
                    # DELETE ALL DOCUMENTS
                    # -----------------------------------------

                    if (
                        intent.name
                        == "delete_all_documents"
                    ):

                        if not document_repository:

                            return SystemResponse(
                                success=False,
                                confidence=intent.confidence,
                                source="document_repository",
                                error=(
                                    "Document repository "
                                    "is unavailable."
                                ),
                            )

                        documents = (
                            await document_repository
                            .list_documents(
                                user_id=user_id
                            )
                        )

                        if not documents:

                            return SystemResponse(
                                success=True,
                                confidence=intent.confidence,
                                source="document_management",
                                data={
                                    "message": (
                                        "You don't have any "
                                        "stored documents to "
                                        "delete, Sir."
                                    )
                                },
                            )

                        return SystemResponse(
                            success=True,
                            confidence=intent.confidence,
                            source="document_management",
                            data={
                                "document_action":
                                    "confirm_delete_all_documents",
                                "documents": documents,
                            },
                        )

                    # -----------------------------------------
                    # DELETE ONE DOCUMENT
                    # -----------------------------------------

                    if (
                        intent.name
                        == "delete_document"
                    ):

                        if not document_repository:

                            return SystemResponse(
                                success=False,
                                confidence=intent.confidence,
                                source="document_repository",
                                error=(
                                    "Document repository "
                                    "is unavailable."
                                ),
                            )

                        documents = (
                            await document_repository
                            .search_documents(
                                user_id=user_id,
                                query=query,
                                limit=10,
                            )
                        )

                        if not documents:

                            documents = (
                                await document_repository
                                .list_documents(
                                    user_id=user_id,
                                    limit=20,
                                )
                            )

                        if not documents:

                            return SystemResponse(
                                success=True,
                                confidence=intent.confidence,
                                source="document_management",
                                data={
                                    "message": (
                                        "I couldn't find that "
                                        "document, Sir."
                                    )
                                },
                            )

                        return SystemResponse(
                            success=True,
                            confidence=intent.confidence,
                            source="document_management",
                            data={
                                "document_action":
                                    "confirm_delete_document",
                                "query": query,
                                "documents": documents,
                            },
                        )

                    # -----------------------------------------
                    # LIST DOCUMENTS
                    # -----------------------------------------

                    if (
                        intent.name
                        == "document_list"
                    ):

                        if not document_repository:

                            return SystemResponse(
                                success=False,
                                confidence=intent.confidence,
                                source="document_repository",
                                error=(
                                    "Document repository "
                                    "is unavailable."
                                ),
                            )

                        documents = (
                            await document_repository
                            .list_documents(
                                user_id=user_id
                            )
                        )

                        if not documents:

                            return SystemResponse(
                                success=True,
                                confidence=intent.confidence,
                                source="document_repository",
                                data={
                                    "message": (
                                        "You don't have any "
                                        "stored documents yet, "
                                        "Sir."
                                    )
                                },
                            )

                        filenames = [
                            doc.get(
                                "filename",
                                "Unnamed document",
                            )
                            for doc in documents
                        ]

                        message = (
                            "I currently have these "
                            "documents, Sir:\n\n"
                            + "\n".join(
                                f"• {name}"
                                for name
                                in filenames
                            )
                        )

                        return SystemResponse(
                            success=True,
                            confidence=intent.confidence,
                            source="document_repository",
                            data={
                                "message": message
                            },
                        )

                    # -----------------------------------------
                    # RETRIEVE DOCUMENT
                    # -----------------------------------------

                    if (
                        intent.name
                        == "document_retrieve"
                    ):

                        if not document_repository:

                            return SystemResponse(
                                success=False,
                                confidence=intent.confidence,
                                source="document_repository",
                                error=(
                                    "Document repository "
                                    "is unavailable."
                                ),
                            )

                        documents = (
                            await document_repository
                            .search_documents(
                                user_id=user_id,
                                query=query,
                                limit=10,
                            )
                        )

                        if not documents:

                            documents = (
                                await document_repository
                                .list_documents(
                                    user_id=user_id,
                                    limit=20,
                                )
                            )

                        if not documents:

                            return SystemResponse(
                                success=True,
                                confidence=intent.confidence,
                                source="document_repository",
                                data={
                                    "message": (
                                        "I couldn't find a "
                                        "stored document "
                                        "matching that request, "
                                        "Sir."
                                    )
                                },
                            )

                        return SystemResponse(
                            success=True,
                            confidence=intent.confidence,
                            source="document_retrieval",
                            data={
                                "document_action":
                                    "send_document",
                                "query": query,
                                "documents": documents,
                            },
                        )

                    # -----------------------------------------
                    # DOCUMENT QUESTION
                    # -----------------------------------------

                    if (
                        intent.name
                        == "document_query"
                    ):

                        if not document_ai:

                            return SystemResponse(
                                success=False,
                                confidence=intent.confidence,
                                source="document",
                                error=(
                                    "Document intelligence "
                                    "is unavailable."
                                ),
                            )

                        answer = (
                            await document_ai.answer_question(
                                session_id=session_id,
                                question=query,
                                state=ctx.get(
                                    "state"
                                ),
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
                                confidence=intent.confidence,
                                source="document",
                                data={
                                    "response": answer
                                },
                            )

                        return SystemResponse(
                            success=True,
                            confidence=intent.confidence,
                            source="document",
                            data={
                                "message": (
                                    "I couldn't find enough "
                                    "information in the stored "
                                    "document to answer that, "
                                    "Sir."
                                )
                            },
                        )

                # =============================================
                # GREETING
                # =============================================

                if intent.name == "greeting":

                    logger.info(
                        "[CognitiveCore] Greeting fast-path "
                        "activated."
                    )

                    return SystemResponse(
                        success=True,
                        confidence=intent.confidence,
                        data={
                            "intent": "greeting",
                            "query": query,
                        },
                        source="greeting_fast_path",
                    )

                # =============================================
                # MEMORY FAST PATH
                # =============================================

                if intent.name in (
                    "memory_recall",
                    "memory_delete",
                ):

                    logger.info(
                        "[CognitiveCore] Memory fast-path "
                        "activated: %s",
                        intent.name,
                    )

                    if (
                        self.memory_conversation_manager
                    ):

                        reply = (
                            await
                            self.memory_conversation_manager
                            .handle(
                                query=query,
                                context=ctx,
                            )
                        )

                        # A non-empty reply means the memory layer was
                        # confident enough to answer directly.
                        if reply and reply.strip():

                            return SystemResponse(
                                success=True,
                                confidence=intent.confidence,
                                data={
                                    "message": reply
                                },
                                source="memory_conversation",
                            )

                        # Relevant memory may exist, but deterministic
                        # recall could not safely formulate the answer.
                        # Continue through ARIA's normal reasoning pipeline.
                        logger.info(
                            "[CognitiveCore] Memory fast-path declined "
                            "direct answer; continuing to semantic reasoning."
                        )

            # =================================================
            # 9. REASONING
            # =================================================

            reasoning = None

            if self.reasoning_engine:

                reasoning = (
                    await self.reasoning_engine.reason(
                        ctx
                    )
                )

                ctx["reasoning"] = reasoning

            state = ctx.get(
                "state",
                {},
            )

            logger.info(
                "[Document] Current state: %s",
                state,
            )

            if state.get(
                "active_document"
            ):

                logger.info(
                    "[Document] Active document detected."
                )

            if reasoning:

                logger.info(
                    "[CognitiveCore] Reasoning complete: "
                    "primary_action=%s confidence=%.2f",
                    reasoning.primary_action,
                    reasoning.confidence,
                )

                ctx["reasoning"] = reasoning

            # =================================================
            # 10. DECISION ENGINE
            # =================================================

            decision = None

            if self.decision_engine:

                decision = (
                    await self.decision_engine.decide(
                        context=ctx,
                        skill_manager=self.skill_manager,
                        planner=self.planner,
                    )
                )

            # -------------------------------------------------
            # Filesystem requests must use Planner + Executor
            # -------------------------------------------------

            if (
                decision
                and looks_like_filesystem_request
            ):
                logger.info(
                    "[CognitiveCore] Overriding routing "
                    "to planner for filesystem request."
                )

                decision.action = "planner"
                decision.confidence = max(
                    getattr(
                        decision,
                        "confidence",
                        0.0,
                    ),
                    0.99,
                )

            # -------------------------------------------------
            # Web-search requests must use Planner + Executor
            # -------------------------------------------------

            looks_like_web_search_request = (
                self._looks_like_web_search_request(
                    query
                )
            )

            if (
                decision
                and looks_like_web_search_request
            ):
                logger.info(
                    "[CognitiveCore] Overriding routing "
                    "to planner for web-search request."
                )

                decision.action = "planner"
                decision.confidence = max(
                    getattr(
                        decision,
                        "confidence",
                        0.0,
                    ),
                    0.99,
                )

            logger.info(
                "[Decision] Selected action: %s",
                (
                    decision.action
                    if decision
                    else None
                ),
            )

            secondary_actions = []

            if decision:

                if (
                    hasattr(
                        decision,
                        "secondary_actions",
                    )
                    and decision.secondary_actions
                ):

                    secondary_actions = (
                        decision.secondary_actions
                    )

                # =============================================
                # DIRECT ACTION
                # =============================================

                if decision.action == "action":

                    # -----------------------------------------
                    # COMPOUND / MULTI-STEP ACTION DETECTION
                    #
                    # A request such as:
                    #
                    # "Read notes.txt and send its content
                    #  as a notification"
                    #
                    # must go through Planner + Executor rather
                    # than being incorrectly treated as one
                    # direct file_action.
                    # -----------------------------------------

                    normalized_action_query = str(
                        query or ""
                    ).strip().lower()

                    compound_connectors = (
                        " and ",
                        " then ",
                        " and then ",
                        " after that ",
                        " afterwards ",
                    )

                    is_compound_action = any(
                        connector in normalized_action_query
                        for connector in compound_connectors
                    )

                    if is_compound_action:

                        logger.info(
                            "[CognitiveCore] Compound action "
                            "detected. Routing to Planner: %s",
                            query,
                        )

                        decision.action = "planner"

                    else:

                        if not self.action_manager:

                            return SystemResponse(
                                success=False,
                                confidence=decision.confidence,
                                source="action_manager",
                                error=(
                                    "Action manager is unavailable."
                                ),
                            )

                        action_name = getattr(
                            reasoning,
                            "action_name",
                            None,
                        )

                        action_params = getattr(
                            reasoning,
                            "action_params",
                            {},
                        )

                        if not action_name:

                            return SystemResponse(
                                success=False,
                                confidence=decision.confidence,
                                source="action_manager",
                                error="No action name specified.",
                            )

                        if (
                            action_name
                            not in self.action_manager.actions
                        ):

                            return SystemResponse(
                                success=False,
                                confidence=decision.confidence,
                                source="action_manager",
                                error=(
                                    f"Action '{action_name}' "
                                    "is not registered."
                                ),
                            )

                        action_instance = (
                            self.action_manager.actions[
                                action_name
                            ]
                        )

                        # -----------------------------------------
                        # DIRECT ACTION CONFIRMATION
                        # -----------------------------------------

                        if (
                            action_instance.permission_level
                            == "confirm"
                        ):

                            if not self.state_manager:

                                return SystemResponse(
                                    success=False,
                                    confidence=decision.confidence,
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

                            logger.info(
                                "[CognitiveCore] Direct action "
                                "awaiting confirmation: %s",
                                action_name,
                            )

                            return SystemResponse(
                                success=True,
                                confidence=decision.confidence,
                                source="action_confirmation",
                                data={
                                    "confirmation_required": True,
                                    "action_name": action_name,
                                    "message": (
                                        "This action requires your "
                                        "confirmation. Shall I continue?"
                                    ),
                                },
                            )

                        # -----------------------------------------
                        # EXECUTE DIRECT ACTION
                        # -----------------------------------------

                        result = (
                            await self.action_manager.execute_action(
                                action_name=action_name,
                                params=action_params,
                            )
                        )

                        if not result.success:

                            return SystemResponse(
                                success=False,
                                confidence=decision.confidence,
                                source="action_manager",
                                error=result.error,
                            )

                        return SystemResponse(
                            success=True,
                            confidence=decision.confidence,
                            source="action_manager",
                            data={
                                "action_name": action_name,
                                "result": result.data,
                            },
                        )

                # =============================================
                # AGENT WORKFLOW
                # =============================================

                if (
                    reasoning
                    and reasoning.workflow
                    and len(
                        reasoning.workflow
                    ) > 0
                    and decision.action
                    not in (
                        "memory_conversation",
                        "document",
                        "delete_document",
                        "delete_all_documents",
                        "reindex_documents",
                        "action",
                        "planner",
                    )
                ):

                    agent_results = []

                    for agent in reasoning.workflow:

                        try:

                            logger.info(
                                "[CognitiveCore] Executing "
                                "agent: %s",
                                agent.name,
                            )

                            result = (
                                await agent.execute(
                                    query,
                                    ctx,
                                )
                            )

                            if (
                                result
                                and result.success
                            ):

                                agent_results.append(
                                    result
                                )

                            elif result:

                                logger.warning(
                                    "[CognitiveCore] Agent "
                                    "%s failed: %s",
                                    agent.name,
                                    result.error,
                                )

                        except Exception:

                            logger.exception(
                                "[CognitiveCore] Agent "
                                "execution failed: %s",
                                getattr(
                                    agent,
                                    "name",
                                    "unknown",
                                ),
                            )

                    if agent_results:

                        fused_response = (
                            self.response_fusion.combine(
                                agent_results
                            )
                        )

                        if fused_response:

                            return SystemResponse(
                                success=True,
                                confidence=max(
                                    result.confidence
                                    for result
                                    in agent_results
                                ),
                                source="agent",
                                data={
                                    "response":
                                        fused_response
                                },
                            )

                # =============================================
                # MEMORY CONVERSATION
                # =============================================

                if (
                    decision.action
                    == "memory_conversation"
                ):

                    if (
                        self.memory_conversation_manager
                    ):

                        reply = (
                            await
                            self.memory_conversation_manager
                            .handle(
                                query=query,
                                context=ctx,
                            )
                        )

                    else:

                        reply = (
                            "Memory conversation manager "
                            "is unconfigured, Sir."
                        )

                    return SystemResponse(
                        success=True,
                        confidence=decision.confidence,
                        data={
                            "message": reply
                        },
                        source="memory",
                    )

                # =============================================
                # DIRECT SKILL
                # =============================================

                elif decision.action == "skill":

                    if (
                        self.skill_manager
                        and hasattr(
                            self.skill_manager,
                            "route_and_execute",
                        )
                    ):

                        skill_res = (
                            await self.skill_manager
                            .route_and_execute(
                                query,
                                ctx,
                            )
                        )

                        if skill_res:

                            return SystemResponse(
                                success=skill_res.success,
                                confidence=(
                                    skill_res.confidence
                                ),
                                data=skill_res.data,
                                source=skill_res.source,
                            )

                # =============================================
                # PLANNER
                # =============================================

                elif decision.action == "planner":

                    # Continue below into Planner + Executor.
                    pass

                # =============================================
                # DOCUMENT
                # =============================================

                elif decision.action == "document":

                    document_ai = ctx.get(
                        "document_intelligence"
                    )

                    if document_ai:

                        answer = (
                            await document_ai
                            .answer_question(
                                session_id=session_id,
                                question=query,
                                state=ctx.get(
                                    "state"
                                ),
                            )
                        )

                        if self.state_manager:

                            self.state_manager.update_state(
                                session_id,
                                last_document_question=query,
                                last_document_answer=answer,
                            )

                        if answer:

                            return SystemResponse(
                                success=True,
                                confidence=decision.confidence,
                                source="document",
                                data={
                                    "response": answer
                                },
                            )

                # =============================================
                # DELETE DOCUMENT
                # =============================================

                elif (
                    decision.action
                    == "delete_document"
                ):

                    document_ai = ctx.get(
                        "document_intelligence"
                    )

                    doc_name = None

                    if hasattr(
                        decision,
                        "data",
                    ):

                        doc_name = (
                            decision.data or {}
                        ).get(
                            "document_name"
                        )

                    if (
                        document_ai
                        and doc_name
                    ):

                        await document_ai.delete_document(
                            session_id=session_id,
                            document_name=doc_name,
                            user_id=user_id,
                        )

                    if self.state_manager:

                        self.state_manager.clear_document_context(
                            session_id
                        )

                    return SystemResponse(
                        success=True,
                        confidence=decision.confidence,
                        source="document_management",
                        data={
                            "response": "Document deleted."
                        },
                    )

                # =============================================
                # DELETE ALL DOCUMENTS
                # =============================================

                elif (
                    decision.action
                    == "delete_all_documents"
                ):

                    document_ai = ctx.get(
                        "document_intelligence"
                    )

                    if document_ai:

                        await document_ai.delete_all_documents(
                            session_id=session_id,
                            user_id=user_id,
                        )

                    if self.state_manager:

                        self.state_manager.clear_document_context(
                            session_id
                        )

                    return SystemResponse(
                        success=True,
                        confidence=decision.confidence,
                        source="document_management",
                        data={
                            "response":
                                "All uploaded documents deleted."
                        },
                    )

                # =============================================
                # REINDEX DOCUMENTS
                # =============================================

                elif (
                    decision.action
                    == "reindex_documents"
                ):

                    document_ai = ctx.get(
                        "document_intelligence"
                    )

                    if document_ai:

                        await document_ai.reindex_documents(
                            session_id
                        )

                    return SystemResponse(
                        success=True,
                        confidence=decision.confidence,
                        source="document_management",
                        data={
                            "response":
                                "Document index rebuilt."
                        },
                    )

                # =============================================
                # CHAT
                # =============================================

                elif decision.action == "chat":

                    if (
                        self.skill_manager
                        and hasattr(
                            self.skill_manager,
                            "route_and_execute",
                        )
                    ):

                        skill_res = (
                            await self.skill_manager
                            .route_and_execute(
                                query,
                                ctx,
                            )
                        )

                        if skill_res:

                            return SystemResponse(
                                success=skill_res.success,
                                confidence=(
                                    skill_res.confidence
                                ),
                                data=skill_res.data,
                                source=skill_res.source,
                            )

            # =================================================
            # 11. PLANNER
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

                plan = self.planner.plan(
                    query,
                    ctx,
                )

            # -------------------------------------------------
            # No orchestration required
            # -------------------------------------------------

            if (
                not plan
                or not getattr(
                    plan,
                    "tasks",
                    None,
                )
            ):

                return SystemResponse(
                    success=True,
                    confidence=getattr(
                        plan,
                        "confidence",
                        0.5,
                    ),
                    data={
                        "intent": "conversational",
                        "query": query,
                    },
                    source="planner_conversational",
                )

            logger.info(
                "[CognitiveCore] Executing plan "
                "with %d task(s).",
                len(plan.tasks),
            )

            # =================================================
            # 12. EXECUTOR
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
            # 13. PAUSE / COMPLETE / FAIL WORKFLOW
            # =================================================

            workflow_response = (
                self._process_workflow_result(
                    session_id=session_id,
                    plan=plan,
                    exec_result=exec_result,
                )
            )

            # -------------------------------------------------
            # Secondary conversational response
            #
            # Only after a completely successful workflow.
            # -------------------------------------------------

            if (
                workflow_response.success
                and isinstance(
                    exec_result,
                    dict,
                )
                and not exec_result.get(
                    "paused",
                    False,
                )
                and secondary_actions
            ):

                final_data = (
                    workflow_response.data
                    if isinstance(
                        workflow_response.data,
                        dict,
                    )
                    else {}
                )

                if "chat" not in final_data:

                    for action in secondary_actions:

                        if action != "chat":
                            continue

                        if (
                            not self.skill_manager
                            or not hasattr(
                                self.skill_manager,
                                "route_and_execute",
                            )
                        ):
                            break

                        chat_res = (
                            await self.skill_manager
                            .route_and_execute(
                                query,
                                ctx,
                            )
                        )

                        if (
                            chat_res
                            and chat_res.success
                        ):

                            final_data[
                                "chat"
                            ] = chat_res.data

                            workflow_response.data = (
                                final_data
                            )

                            break

            return workflow_response

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
