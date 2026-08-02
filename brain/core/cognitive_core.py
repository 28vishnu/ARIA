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

        self.brain_state = {
            "thinking": False,
            "learning": False,
            "reasoning": False,
            "retrieving": False,
        }

        self.response_formatter = ResponseFormatter()
        self.response_fusion = ResponseFusion()

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
        ARIA's core knowledge-first intelligence pipeline.
        Executes parallel retrieval and strict prioritization:
        1. Personal Memory
        2. Documents
        3. Knowledge Graph
        4. Knowledge Database
        5. World Model
        6. Skills
        7. Web Search -> Learn -> LLM -> Summarize -> Store
        8. Automatic Learning & Reflection
        9. Personality Engine
        """
        self.brain_state["retrieving"] = True
        answer = None
        source = "llm_generated"
        confidence = 0.5

        try:
            # Parallel Retrieval across subsystems (using resolved query via context/parameters)
            memory_task = (
                self.memory_router.answer(query)
                if self.memory_router and hasattr(self.memory_router, "answer")
                else asyncio.sleep(0)
            )
            doc_task = (
                self.knowledge_manager.answer(session_id, query)
                if self.knowledge_manager and hasattr(self.knowledge_manager, "answer")
                else asyncio.sleep(0)
            )
            graph_task = (
                self.knowledge_graph.search(query)
                if self.knowledge_graph and hasattr(self.knowledge_graph, "search")
                else asyncio.sleep(0)
            )
            db_task = (
                self.knowledge_database.search(query)
                if self.knowledge_database and hasattr(self.knowledge_database, "search")
                else asyncio.sleep(0)
            )
            world_task = (
                asyncio.to_thread(self.world_model.search, query)
                if self.world_model and hasattr(self.world_model, "search")
                else asyncio.sleep(0)
            )

            results = await asyncio.gather(
                memory_task,
                doc_task,
                graph_task,
                db_task,
                world_task,
                return_exceptions=True,
            )

            mem_res, doc_res, graph_res, db_res, world_res = [
                r if not isinstance(r, Exception) else None for r in results
            ]

            # Confidence Ranking / Prioritization Selection (Priority: Memory -> Documents -> Graph -> Database -> World Model)
            if mem_res:
                if isinstance(mem_res, str):
                    answer = mem_res
                    source = "memory"
                    confidence = 0.94
                elif isinstance(mem_res, list):
                    cleaned_memories = []
                    for m in mem_res:
                        if isinstance(m, dict):
                            k = m.get("key", "").replace("_", " ").title()
                            v = m.get("value", "")
                            if k and v:
                                cleaned_memories.append(f"- {k}: {v}")
                        elif isinstance(m, str):
                            cleaned_memories.append(f"- {m}")
                    context["memory"] = cleaned_memories
                elif isinstance(mem_res, dict):
                    m = mem_res
                    k = m.get("key", "").replace("_", " ").title()
                    v = m.get("value", "")
                    context["memory"] = [f"- {k}: {v}"] if k and v else [str(m)]

            if not answer and doc_res:
                answer = doc_res
                source = "document"
                confidence = 0.89
                if self.world_model and hasattr(self.world_model, "set_active_document"):
                    self.world_model.set_active_document(query)
                if self.event_bus:
                    await self.event_bus.publish(
                        Event(
                            type=event_types.DOCUMENT_PROCESSED,
                            source="cognitive_core",
                            data={
                                "query": query,
                                "answer": answer,
                            }
                        )
                    )
            elif not answer and graph_res:
                answer = str(graph_res)
                source = "knowledge_graph"
                confidence = 0.81
            elif not answer and db_res:
                answer = str(db_res)
                source = "knowledge_database"
                confidence = 0.75
            elif not answer and world_res:
                answer = str(world_res)
                source = "world_model"
                confidence = 0.91

            # Step 4 & 5: Skills Fallback if no knowledge/memory hit
            if not answer and self.skill_manager and hasattr(self.skill_manager, "route_and_execute"):
                try:
                    skill_result = await self.skill_manager.route_and_execute(
                        query,
                        context,
                    )
                    if skill_result and skill_result.success:
                        answer = (
                            skill_result.data.get("response")
                            or skill_result.data.get("message")
                            or str(skill_result.data)
                        )
                        source = "skill"
                        confidence = 0.80
                except Exception:
                    logger.exception("[CognitiveCore] Skills execution failed.")

            # Step 6 & 10 & 11: Web Search -> Learn -> LLM Fallback (Cache if found)
            if not answer:
                self.brain_state["thinking"] = True
                if self._looks_like_web_search_request(query) and self.action_manager and "web_search" in self.action_manager.actions:
                    try:
                        web_result = await self.action_manager.execute_action(
                            action_name="web_search",
                            params={"query": query},
                        )
                        if web_result and web_result.success:
                            answer = (
                                web_result.data.get("result")
                                or web_result.data.get("content")
                                or str(web_result.data)
                            )
                            source = "web_search"
                            confidence = 0.70
                    except Exception:
                        logger.exception("[CognitiveCore] Web Search failed.")

                if not answer:
                    try:
                        if self.reasoning_engine:
                            reasoning = await self.reasoning_engine.reason(context)
                            context["reasoning"] = reasoning

                        if self.planner:
                            plan = await self.planner.create_plan(query, context)
                            if plan and plan.tasks and self.executor:
                                exec_result = await self.executor.execute_plan(plan, context)
                                task_outputs = exec_result.get("task_outputs", {})
                                for task in reversed(plan.tasks):
                                    out = task_outputs.get(task.id, {})
                                    if isinstance(out, dict):
                                        answer = out.get("response") or out.get("content") or out.get("message")
                                        if answer:
                                            break
                                if self.event_bus:
                                    await self.event_bus.publish(
                                        Event(
                                            type=event_types.PLAN_COMPLETED,
                                            source="planner",
                                            data={
                                                "query": query,
                                            }
                                        )
                                    )

                        if not answer and self.llm_router and hasattr(self.llm_router, "chat"):
                            conversation = context.get("conversation", {})
                            
                            conversation.setdefault("history", [])
                            if not conversation["history"] and self.state_manager:
                                try:
                                    conversation["history"] = self.state_manager.get_conversation_history(session_id) or []
                                except Exception:
                                    pass

                            memory_items = context.get("memory", [])
                            document = context.get("document", {})
                            knowledge = context.get("knowledge", {})

                            memories_str = "\n".join(memory_items) if isinstance(memory_items, list) else str(memory_items)
                            if not memories_str.strip():
                                memories_str = "None recorded."

                            doc_str = str(document) if document else "None"
                            knowledge_str = str(knowledge) if knowledge else "None"

                            # Requirement 4: Get conversation context and inject into system prompt
                            conversation_context = {}
                            if self.conversation_manager:
                                conversation_context = self.conversation_manager.get_context(session_id)

                            system_prompt = f"""You are ARIA, an advanced personal AI collaborator.

Conversation Context:

Current Topic:
{conversation_context.get("topic")}

Previous Topic:
{conversation_context.get("previous_topic")}

Last User Message:
{conversation_context.get("last_user")}

Last Assistant Message:
{conversation_context.get("last_assistant")}

Relevant user memories:
{memories_str}

Active document:
{doc_str}

Relevant knowledge:
{knowledge_str}
"""

                            messages = [
                                {
                                    "role": "system",
                                    "content": system_prompt
                                }
                            ]

                            for turn in conversation.get("history", []):
                                if not isinstance(turn, dict):
                                    continue

                                user_turn = turn.get("user")
                                assistant_turn = turn.get("assistant")

                                if user_turn:
                                    messages.append({
                                        "role": "user",
                                        "content": str(user_turn)
                                    })

                                if assistant_turn:
                                    messages.append({
                                        "role": "assistant",
                                        "content": str(assistant_turn)
                                    })

                            # Sending resolved_query to the LLM instead of raw user_message
                            messages.append({
                                "role": "user",
                                "content": query
                            })

                            answer = await self.llm_router.chat(messages)
                    except Exception:
                        logger.exception("[CognitiveCore] LLM/Reasoning fallback failed.")

                if not answer:
                    answer = "I couldn't find the information to answer your request."
                    confidence = 0.1

                if source != "llm_generated" or confidence > 0.85:
                    if self.knowledge_database and hasattr(self.knowledge_database, "store"):
                        await self.knowledge_database.store(title=query[:50], content=answer, source=source)
                    if self.knowledge_graph and hasattr(self.knowledge_graph, "learn"):
                        await self.knowledge_graph.learn(query, answer)

        finally:
            self.brain_state["retrieving"] = False
            self.brain_state["thinking"] = False
            self.brain_state["reasoning"] = False

        if self.state_manager:
            try:
                self.state_manager.update_state(
                    session_id,
                    last_reasoning=context.get("reasoning"),
                    last_source=source,
                    last_confidence=confidence,
                    last_assistant_response=answer,
                )
            except Exception:
                logger.exception("[CognitiveCore] Failed to update state with execution metadata.")

        if self.event_bus:
            await self.event_bus.publish(
                Event(
                    type=event_types.RESPONSE_GENERATED,
                    source="cognitive_core",
                    data={
                        "query": query,
                        "answer": answer,
                        "confidence": confidence,
                        "knowledge_source": source,
                        "session_id": session_id,
                    }
                )
            )

        return await self._format_response(answer, source, context, confidence)

    async def _format_response(self, answer: str, source: str, context: Dict[str, Any], confidence: float = 1.0) -> SystemResponse:
        formatted_answer = answer
        if self.personality_engine and hasattr(self.personality_engine, "format"):
            try:
                formatted_answer = await self.personality_engine.format(answer, context)
            except Exception:
                logger.exception("[CognitiveCore] PersonalityEngine formatting failed.")

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

    # Requirement 1: Automatic entity extraction helper method
    def _extract_entities(self, text: str):
        """
        Simple fallback entity extractor.
        Later this can be replaced with spaCy or LLM extraction.
        """
        entities = []

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
            # Step 1: Initialize session and obtain user message & session ID
            user_message = query
            session = self.conversation_manager.get_session(session_id) if self.conversation_manager else {}

            # Step 2: Resolve reference if it's a follow-up
            resolved_query = user_message
            if self.conversation_manager and self.conversation_manager.is_followup(user_message):
                resolved_query = self.conversation_manager.resolve_reference(
                    session_id,
                    user_message
                )

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
                    query=resolved_query,
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
                    self._normalize_confirmation_text(resolved_query)
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
            # 4. RETRIEVE RELEVANT MEMORY VIA ROUTER (using resolved_query)
            # =================================================

            memories = []

            if self.memory_router:

                try:
                    memories = (
                        await self.memory_router.recall(resolved_query)
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
                    query=resolved_query,
                    session_id=session_id,
                    user_id=user_id,
                    base_context=base_context,
                    memory=memories,
                    state=state,
                )

            else:

                ctx = dict(base_context or {})

                ctx["query"] = resolved_query
                ctx["session_id"] = session_id
                ctx["user_id"] = user_id
                ctx["state"] = state
                ctx["memory"] = memories

            # Guarantee essential context exists even if the
            # ContextBuilder omitted one of these fields.

            ctx.setdefault("query", resolved_query)
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
                    last_query=resolved_query,
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
                        await self.intent_analyzer.analyze(resolved_query)
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
                        query=resolved_query,
                        context=ctx,
                    )
                )

                # Requirement 2: Replace entities=[] with robust entity building
                if self.conversation_manager:
                    intent_name = getattr(intent, "name", None)
                    entities = []

                    if intent and hasattr(intent, "entities"):
                        entities = intent.entities or []

                    if not entities:
                        entities = self._extract_entities(resolved_query)

                    self.conversation_manager.update_turn(
                        session_id=session_id,
                        user_message=user_message,
                        assistant_message=reply,
                        intent=intent_name,
                        entities=entities,
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
            # 10. NATURAL MEMORY LEARNING VIA ROUTER (using resolved_query)
            # =================================================

            if self.memory_router:

                try:

                    memory_result = (
                        await self.memory_router
                        .remember(resolved_query)
                    )

                    if (
                        memory_result
                        and memory_result.get("success")
                    ):

                        logger.info(
                            "[CognitiveCore] Natural memory "
                            "learning via router: key=%s action=%s",
                            memory_result.get("key"),
                            memory_result.get("action"),
                        )

                        if self.event_bus:
                            await self.event_bus.publish(
                                Event(
                                    type=event_types.MEMORY_CREATED,
                                    source="memory",
                                    data={
                                        "query": resolved_query,
                                    }
                                )
                            )

                        try:

                            refreshed = (
                                await self.memory_router
                                .recall(resolved_query)
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
            # 11. KNOWLEDGE-FIRST PIPELINE EXECUTION (using resolved_query)
            # =================================================

            self.brain_state["thinking"] = True
            self.brain_state["reasoning"] = True
            pipeline_response = await self.knowledge_first_pipeline(
                session_id,
                resolved_query,
                ctx,
            )

            # Requirement 2 & 3: Robust entity building, update_turn call, and conversation history storage
            if self.conversation_manager:
                final_reply = pipeline_response.data.get("response") or pipeline_response.data.get("message") or ""
                intent_name = getattr(intent, "name", None) if intent else None

                entities = []

                if intent and hasattr(intent, "entities"):
                    entities = intent.entities or []

                if not entities:
                    entities = self._extract_entities(resolved_query)

                self.conversation_manager.update_turn(
                    session_id=session_id,
                    user_message=user_message,
                    assistant_message=str(final_reply),
                    intent=intent_name,
                    entities=entities,
                )

                if self.state_manager:
                    try:
                        self.state_manager.append_conversation_history(
                            session_id=session_id,
                            user=user_message,
                            assistant=str(final_reply),
                        )
                    except Exception:
                        logger.exception("[CognitiveCore] Failed to store conversation history.")

            return pipeline_response

        # =====================================================
        # GLOBAL ERROR HANDLER
        # =====================================================

        except Exception as exc:

            logger.exception(
                "[CognitiveCore ERROR] Processing failed: %s",
                exc,
            )

            if self.event_bus:
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

            return SystemResponse(
                success=False,
                confidence=0.0,
                source="cognitive_core",
                error=str(exc),
            )
