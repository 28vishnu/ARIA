import logging
import asyncio
import re
from typing import Dict, Any, Optional, List

from personality.response import SystemResponse
from brain.response.response_formatter import ResponseFormatter
from brain.agents.response_fusion import ResponseFusion
from brain.events.event import Event
from brain.events import event_types

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
        knowledge_graph=None,
        knowledge_database=None,
        learning_engine=None,
        personality_engine=None,
        world_model=None,
        self_reflection=None,
        autonomous_learning=None,
        event_bus=None,
        llm_router=None,
        conversation_manager=None,
        working_memory=None,
        memory_engine=None,
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
        self.knowledge_graph = knowledge_graph
        self.knowledge_database = knowledge_database
        self.learning_engine = learning_engine
        self.personality_engine = personality_engine
        self.world_model = world_model
        self.self_reflection = self_reflection
        self.autonomous_learning = autonomous_learning
        self.event_bus = event_bus
        self.llm_router = llm_router
        self.conversation_manager = conversation_manager
        self.working_memory = working_memory
        self.memory_engine = memory_engine

        self.brain_state = {
            "thinking": False,
            "learning": False,
            "reasoning": False,
            "retrieving": False,
        }

        self.response_formatter = ResponseFormatter()
        self.response_fusion = ResponseFusion()

    async def _resolve_query(self, session_id: str, query: str) -> str:
        history = []

        if self.state_manager:
            try:
                history = self.state_manager.get_conversation_history(session_id)
            except Exception as e:
                logger.warning("State manager conversation history retrieval skipped: %s", e)

        if not history:
            return query

        messages = [
            {
                "role": "system",
                "content": (
                    "Rewrite follow-up questions into standalone questions. "
                    "Return ONLY the rewritten question."
                ),
            }
        ]

        for turn in history[-5:]:
            messages.append({"role": "user", "content": turn["user"]})
            messages.append({"role": "assistant", "content": turn["assistant"]})

        messages.append({"role": "user", "content": query})

        resolved = None
        if self.llm_router and hasattr(self.llm_router, "chat"):
            try:
                resolved = await self.llm_router.chat(messages)
            except Exception as e:
                logger.warning("LLM router chat for resolution skipped: %s", e)

        return resolved.strip() if resolved else query

    # =========================================================
    # KNOWLEDGE FIRST PIPELINE
    # =========================================================

    async def knowledge_first_pipeline(
        self,
        session_id: str,
        query: str,
        context: Dict[str, Any],
    ) -> SystemResponse:
        """
        ARIA's core unified cognitive intelligence pipeline orchestrated via Reasoning, Planner, Executor, Memory, WorldModel, Reflection, and Learning.
        """
        self.brain_state["retrieving"] = True
        answer = None
        source = "llm_generated"
        confidence = 0.5

        if self.reasoning_engine:
            resolved_query = await self.reasoning_engine.resolve_references(
                query,
                context,
            )
        else:
            resolved_query = query

        # Step 1: Build context first via context_builder if available
        if self.context_builder:
            try:
                context = await self.context_builder.build(
                    query=resolved_query,
                    session_id=session_id,
                    user_id=context.get("user_id", session_id),
                    base_context=context,
                )
            except Exception as e:
                logger.warning("Context builder skipped: %s", e)
                context.setdefault("query", resolved_query)
                context.setdefault("session_id", session_id)
        else:
            context.setdefault("query", resolved_query)
            context.setdefault("session_id", session_id)

        # Build working memory context with updated priority ordering
        working_memory_context = {}
        if self.working_memory:
            working_memory_context = {
                "topic": self.working_memory.get_topic(),
                "goal": self.working_memory.get_goal(),
                "entities": self.working_memory.get_entities(),
                "recent_results": getattr(self.working_memory, "get_recent_results", lambda: [])(),
            }

        conversation_context = context.get("conversation", {})
        memory_context = context.get("memory", [])
        world_state = context.get("world", {})

        # Re-prioritize context fields according to new hierarchy
        context = {
            "query": resolved_query,
            "working_memory": working_memory_context,
            "conversation": conversation_context,
            "memory": memory_context,
            "world": world_state,
        }

        # Step 2: Call the reasoning engine immediately
        reasoning = None
        if self.reasoning_engine:
            try:
                reasoning = await self.reasoning_engine.reason(context)
                context["reasoning"] = reasoning
            except Exception as e:
                logger.warning("ReasoningEngine invocation skipped: %s", e)

        # =========================================================
        # REASONING -> AGENTS -> PLANNER -> EXECUTOR FLOW
        # =========================================================
        selected_agents = []
        needs_execution = False
        execution_result = None
        plan = None

        if reasoning:
            selected_agents = getattr(reasoning, "selected_agents", []) or []

        needs_execution = any(
            agent != "chat"
            for agent in selected_agents
        )

        logger.info(
            "[CognitiveCore] Selected agents: %s",
            selected_agents
        )

        logger.info(
            "[CognitiveCore] Execution required: %s",
            needs_execution
        )

        if needs_execution and self.planner and self.executor:
            try:
                plan = self.planner.create_task_graph(resolved_query)
                execution_result = await self.executor.execute_plan(
                    plan,
                    context=context
                )
                if isinstance(reasoning, dict):
                    reasoning["execution_result"] = execution_result
                    reasoning["task_plan"] = plan
                elif reasoning is not None:
                    setattr(reasoning, "execution_result", execution_result)
                    setattr(reasoning, "task_plan", plan)
            except Exception as e:
                logger.warning("Planner/Executor execution failed: %s", e)

        try:
            # Step 3: If reasoning already contains an answer
            if reasoning and getattr(reasoning, "answer", None):
                answer = reasoning.answer
                source = "reasoning"
                confidence = getattr(reasoning, "confidence", 0.90)

            # Step 4: If reasoning generated a plan, execute it via the executor
            if not answer and reasoning and getattr(reasoning, "plan", None) and self.executor:
                try:
                    result = await self.executor.execute_plan(
                        reasoning.plan,
                        context,
                    )
                    if result:
                        answer = result.get("response") or result.get("message") or (result.get("task_outputs") and str(result.get("task_outputs")))
                        if answer:
                            source = "planner_executor"
                            confidence = getattr(reasoning, "plan", {}).get("confidence", 0.92)
                except Exception as e:
                    logger.warning("Executor plan execution skipped: %s", e)

            # Step 5: Only if there is still no answer, fallback to Memory -> Knowledge -> World -> LLM
            if not answer:
                self.brain_state["thinking"] = True

                # Memory Subsystem
                mem_res = None
                if reasoning and getattr(reasoning, "retrieved_memory", None):
                    mem_res = reasoning.retrieved_memory
                elif self.memory_router and hasattr(self.memory_router, "answer"):
                    try:
                        mem_res = await self.memory_router.answer(resolved_query, reasoning_result=reasoning)
                    except Exception as e:
                        logger.warning("Memory router answer search skipped: %s", e)

                if mem_res:
                    if isinstance(mem_res, str):
                        answer = mem_res
                        source = "memory"
                        confidence = 0.94
                    elif isinstance(mem_res, list) and mem_res:
                        answer = str(mem_res)
                        source = "memory"
                        confidence = 0.94

                # Knowledge Subsystem
                if not answer:
                    doc_res = None
                    try:
                        if self.knowledge_manager and hasattr(self.knowledge_manager, "answer"):
                            doc_res = await self.knowledge_manager.answer(
                                session_id=session_id,
                                question=resolved_query,
                            )
                    except Exception as e:
                        logger.warning("KnowledgeManager skipped: %s", e)
                        doc_res = None

                    if doc_res:
                        answer = doc_res
                        source = "document"
                        confidence = 0.89
                    elif reasoning and getattr(reasoning, "graph_results", None):
                        answer = str(reasoning.graph_results)
                        source = "knowledge_graph"
                        confidence = 0.81
                    elif self.knowledge_database and hasattr(self.knowledge_database, "search"):
                        try:
                            db_res = await self.knowledge_database.search(resolved_query)
                            if db_res:
                                answer = str(db_res)
                                source = "knowledge_database"
                                confidence = 0.75
                        except Exception as e:
                            logger.warning("Knowledge database search skipped: %s", e)

                # World Model Subsystem
                if not answer:
                    world_res = None
                    if reasoning and hasattr(reasoning, "world_state"):
                        world_res = reasoning.world_state
                    elif self.world_model and hasattr(self.world_model, "search"):
                        try:
                            world_res = await asyncio.to_thread(self.world_model.search, resolved_query)
                        except Exception as e:
                            logger.warning("World model search skipped: %s", e)
                    if world_res:
                        answer = str(world_res)
                        source = "world_model"
                        confidence = 0.91

                # LLM Fallback (only if required)
                if not answer and self.llm_router and hasattr(self.llm_router, "chat"):
                    try:
                        system_context = (
                            "You are ARIA.\n\n"
                            "Behave like a trusted AI assistant.\n"
                            "Understand what the user is trying to achieve, not only what they asked.\n"
                            "Answer naturally.\n"
                            "Be concise.\n"
                            "Avoid sounding like an encyclopedia.\n"
                            "Use conversation history when relevant.\n"
                            "If a useful next step exists, suggest it naturally.\n"
                            "Never pad the answer."
                        )

                        if execution_result:
                            system_context += f"""

Execution Results:

{execution_result}

"""

                        messages = [
                            {
                                "role": "system",
                                "content": system_context
                            },
                            {
                                "role": "user",
                                "content": resolved_query
                            }
                        ]
                        answer = await self.llm_router.chat(messages)
                        source = "llm_generated"
                        confidence = 0.70
                    except Exception as e:
                        logger.warning("LLM fallback generation skipped: %s", e)

                if not answer:
                    answer = "I couldn't find the information to answer your request."
                    confidence = 0.1

        finally:
            self.brain_state["retrieving"] = False
            self.brain_state["thinking"] = False
            self.brain_state["reasoning"] = False

        # Step 6: Reflection and Learning hooks before returning
        if self.self_reflection:
            try:
                await self.self_reflection.reflect(
                    session_id,
                    resolved_query,
                    answer,
                )
            except Exception as e:
                logger.warning("Self reflection skipped: %s", e)

        if self.autonomous_learning:
            try:
                await self.autonomous_learning.learn(
                    session_id,
                    resolved_query,
                    answer,
                )
            except Exception as e:
                logger.warning("Autonomous learning skipped: %s", e)

        if self.state_manager:
            try:
                self.state_manager.update_state(
                    session_id,
                    last_reasoning=context.get("reasoning"),
                    last_source=source,
                    last_confidence=confidence,
                    last_assistant_response=answer,
                )
            except Exception as e:
                logger.warning("State manager update skipped: %s", e)

        if self.event_bus:
            try:
                await self.event_bus.publish(
                    Event(
                        type=event_types.RESPONSE_GENERATED,
                        source="cognitive_core",
                        data={
                            "query": resolved_query,
                            "answer": answer,
                            "confidence": confidence,
                            "knowledge_source": source,
                            "session_id": session_id,
                        }
                    )
                )
            except Exception as e:
                logger.warning("Event bus publish skipped: %s", e)

        # Synchronization steps after response generation
        formatted_response = await self._format_response(answer, source, context, confidence)
        response_text = formatted_response.data.get("response", answer)

        if self.working_memory and context.get("active_context", {}).get("topic"):
            self.working_memory.set_topic(
                context["active_context"]["topic"]
            )

        if self.working_memory:
            self.working_memory.remember_exchange(
                resolved_query,
                response_text
            )

        if self.conversation_manager:
            try:
                self.conversation_manager.update_turn(
                    session_id=session_id,
                    user_message=resolved_query,
                    assistant_message=response_text,
                )
            except Exception as e:
                logger.warning("Conversation manager update_turn skipped: %s", e)

        if self.state_manager:
            try:
                self.state_manager.add_conversation_turn(
                    session_id=session_id,
                    user_message=resolved_query,
                    assistant_message=response_text,
                )
            except Exception as e:
                logger.warning("State manager add_conversation_turn skipped: %s", e)

        topic = context.get("active_context", {}).get("topic")
        if topic and self.world_model:
            try:
                if hasattr(self.world_model, "set_active_topic"):
                    res = self.world_model.set_active_topic(topic)
                    if asyncio.iscoroutine(res):
                        await res
            except Exception as e:
                logger.warning("WorldModel set_active_topic skipped: %s", e)

        entities = context.get("active_context", {}).get("entities", [])
        if self.working_memory and entities:
            self.working_memory.set_entities(entities)

        return formatted_response

    async def _format_response(self, answer: str, source: str, context: Dict[str, Any], confidence: float = 1.0) -> SystemResponse:
        formatted_answer = answer
        if self.personality_engine and hasattr(self.personality_engine, "format"):
            try:
                formatted_answer = await self.personality_engine.format(answer, context)
            except Exception as e:
                logger.warning("Personality engine formatting skipped: %s", e)

        return SystemResponse(
            success=True,
            confidence=confidence,
            source=source,
            data={
                "response": formatted_answer,
                "message": formatted_answer,
            },
        )

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

    def _extract_entities(self, text: str):
        COMMON_TOPICS = {
            "python",
            "java",
            "javascript",
            "c++",
            "linux",
            "docker",
            "mongodb",
            "postgres",
            "redis",
            "fastapi",
            "django",
            "flask",
        }

        entities = []

        for word in text.lower().split():
            cleaned = word.strip(".,?!")
            if cleaned in COMMON_TOPICS:
                entities.append(cleaned.title())

        for match in re.findall(r"\b[A-Z][a-zA-Z0-9_]+\b", text):
            if match not in entities:
                entities.append(match)

        return entities

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
        Main cognitive orchestration pipeline guided by ReasoningEngine.
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
            # 2. RESOLVE FOLLOW-UP REFERENCES
            # =================================================

            if self.conversation_manager:
                try:
                    if self.conversation_manager.is_followup(query):
                        query = self.conversation_manager.resolve_reference(
                            session_id,
                            query,
                        )
                except Exception as e:
                    logger.warning("Conversation manager resolution skipped: %s", e)

            # =================================================
            # 3. RESUME / CANCEL PENDING WORKFLOW
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
            # 4. HANDLE PENDING DIRECT ACTION
            # =================================================

            if (
                self.state_manager
                and state.get("pending_action_confirmation")
            ):

                normalized_query = (
                    self._normalize_confirmation_text(query)
                )

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

                if self._is_reject(normalized_query):

                    action_name = state.get(
                        "pending_action_name"
                    )

                    self.state_manager.clear_pending_action(
                        session_id
                    )

                    return SystemResponse(
                        success=True,
                        confidence=1.0,
                        source="action_confirmation",
                        data={
                            "message": "Action cancelled."
                        },
                    )

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
            # 5. REASONING ENGINE INTEGRATION (Central Control)
            # =================================================
            pre_ctx = dict(base_context or {})
            pre_ctx["query"] = query
            pre_ctx["session_id"] = session_id
            pre_ctx["user_id"] = user_id
            pre_ctx["state"] = state

            reasoning = None
            if self.reasoning_engine and hasattr(self.reasoning_engine, "reason"):
                try:
                    reasoning = await self.reasoning_engine.reason(pre_ctx)
                except Exception:
                    logger.exception("[CognitiveCore] Initial ReasoningEngine invocation failed.")

            # =================================================
            # 6. RETRIEVE RELEVANT MEMORY CONDITIONALLY VIA ROUTER / ENGINE
            # =================================================

            memories = []

            if self.memory_engine and reasoning and getattr(reasoning, "requires_memory", False):
                try:
                    memories = await self.memory_engine.retrieve(query) or []
                except Exception:
                    logger.exception("[CognitiveCore] Memory engine retrieval failed.")
            elif self.memory_router and reasoning and getattr(reasoning, "requires_memory", False):
                try:
                    memories = (
                        await self.memory_router.recall(query)
                    ) or []

                except Exception:
                    logger.exception(
                        "[CognitiveCore] Memory retrieval failed."
                    )

            # =================================================
            # 7. BUILD COMPLETE CONTEXT
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

            ctx.setdefault("query", query)
            ctx.setdefault("session_id", session_id)
            ctx.setdefault("user_id", user_id)
            ctx.setdefault("state", state)
            ctx.setdefault("memory", memories)

            if reasoning:
                ctx["reasoning"] = reasoning

            # =================================================
            # 8. ATTACH REGISTERED CAPABILITIES
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
            # 9. SAVE CURRENT QUERY
            # =================================================

            if self.state_manager:
                try:
                    self.state_manager.update_state(
                        session_id,
                        last_query=query,
                    )
                except Exception as e:
                    logger.warning("State manager update skipped: %s", e)

            # =================================================
            # 10. INTENT ANALYSIS
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
            # 11. EXPLICIT MEMORY MANAGEMENT
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
            # 12. NATURAL MEMORY LEARNING VIA ROUTER
            # =================================================

            if self.memory_router:

                try:

                    memory_result = (
                        await self.memory_router
                        .remember(query)
                    )

                    if (
                        memory_result
                        and memory_result.get("success")
                    ):

                        if self.event_bus:
                            try:
                                await self.event_bus.publish(
                                    Event(
                                        type=event_types.MEMORY_CREATED,
                                        source="memory",
                                        data={
                                            "query": query,
                                        }
                                    )
                                )
                            except Exception as e:
                                logger.warning("Event bus publish skipped: %s", e)

                        try:

                            refreshed = (
                                await self.memory_router
                                .recall(query)
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
            # 13. KNOWLEDGE-FIRST PIPELINE EXECUTION
            # =================================================

            self.brain_state["thinking"] = True
            self.brain_state["reasoning"] = True
            return await self.knowledge_first_pipeline(
                session_id,
                query,
                ctx,
            )

        # =====================================================
        # GLOBAL ERROR HANDLER
        # =====================================================

        except Exception as exc:

            logger.exception(
                "[CognitiveCore ERROR] Processing failed: %s",
                exc,
            )

            if self.event_bus:
                try:
                    await self.event_bus.publish(
                        Event(
                            type=event_types.ERROR_OCCURRED,
                            source="cognitive_core",
                            data={
                                "query": query,
                                "error": str(exc),
                            }
                        )
                    )
                except Exception as e:
                    logger.warning("Event bus error publish skipped: %s", e)

            return SystemResponse(
                success=False,
                confidence=0.0,
                source="cognitive_core",
                error=str(exc),
            )
