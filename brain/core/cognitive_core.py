# Brain/core/cognitive_core.py

import logging
import asyncio
import re
from typing import Dict, Any, Optional, List

from personality.response import SystemResponse
from brain.response.response_formatter import ResponseFormatter
from brain.agents.response_fusion import ResponseFusion
from brain.events.event import Event
from brain.events import event_types
from brain.core.cognitive_controller import CognitiveController
from brain.core.prompt_builder import PromptBuilder
from brain.core.fast_router import should_fast_route
from brain.core.execution_router import decide, Route
from brain.core.coding_engine import CodingEngine
from brain.core.engine_manager import EngineManager

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
        goal_manager=None,
        project_manager=None,
        task_manager=None,
        agent_coordinator=None,
        lead_agent=None,
        document_pipeline=None,
        study_engine=None,
        repository_memory=None,
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
        self.goal_manager = goal_manager
        self.project_manager = project_manager
        self.task_manager = task_manager
        self.agent_coordinator = agent_coordinator
        self.lead_agent = lead_agent
        self.document_pipeline = document_pipeline
        self.study_engine = study_engine
        self.repository_memory = repository_memory
        self.cognitive_controller = CognitiveController()
        self.prompt_builder = PromptBuilder()
        self.coding_engine = CodingEngine(self.llm_router)
        self.engine_manager = EngineManager()
        self.engine_manager.register(
            "coding",
            self.coding_engine,
        )

        self.brain_state = {
            "thinking": False,
            "learning": False,
            "reasoning": False,
            "retrieving": False,
        }

        self.response_formatter = ResponseFormatter()
        self.response_fusion = ResponseFusion()

    def _extract_weather_params(self, query: str) -> Dict[str, Any]:
        """
        Extract structured weather parameters from a natural-language
        weather request.

        Examples:
            Weather in London
                -> location=London, forecast_days=1

            Weather in London tomorrow
                -> location=London, forecast_days=2,
                   forecast_target=tomorrow

            Weather in Tokyo for 5 days
                -> location=Tokyo, forecast_days=5

            Will it rain in Mumbai tomorrow?
                -> location=Mumbai, forecast_days=2,
                   forecast_target=tomorrow
        """

        text = str(query or "").strip()

        if not text:
            return {
                "location": "",
                "forecast_days": 1,
                "forecast_target": "today",
            }

        working = text

        # ---------------------------------------------------------
        # Detect forecast target
        # ---------------------------------------------------------

        forecast_target = "today"

        if re.search(r"\btomorrow\b", working, re.IGNORECASE):
            forecast_target = "tomorrow"

        elif re.search(
            r"\b(?:today|right now|currently|current|now)\b",
            working,
            re.IGNORECASE,
        ):
            forecast_target = "today"

        # ---------------------------------------------------------
        # Detect explicit forecast length
        # ---------------------------------------------------------

        forecast_days = 1

        days_match = re.search(
            r"\b(?:for|next)\s+(\d+)\s+days?\b",
            working,
            re.IGNORECASE,
        )

        if days_match:
            try:
                forecast_days = int(days_match.group(1))
            except (TypeError, ValueError):
                forecast_days = 1

        # Tomorrow requires at least two forecast days so that
        # WeatherAction can access the second day.
        if forecast_target == "tomorrow":
            forecast_days = max(forecast_days, 2)

        forecast_days = max(1, min(forecast_days, 7))

        # ---------------------------------------------------------
        # Remove temporal phrases before passing the query to
        # WeatherAction.
        # ---------------------------------------------------------

        location_query = re.sub(
            r"\b(?:tomorrow|today|right now|currently|current|now)\b",
            "",
            working,
            flags=re.IGNORECASE,
        )

        location_query = re.sub(
            r"\b(?:for|next)\s+\d+\s+days?\b",
            "",
            location_query,
            flags=re.IGNORECASE,
        )

        location_query = re.sub(
            r"\s+",
            " ",
            location_query,
        ).strip(" ,.?")

        # ---------------------------------------------------------
        # Remove common weather question wording.
        #
        # WeatherAction already performs its own extraction, but
        # removing temporal language here prevents it from becoming
        # part of the geocoding query.
        # ---------------------------------------------------------

        return {
            "location": location_query,
            "forecast_days": forecast_days,
            "forecast_target": forecast_target,
        }

    def _extract_timezone(self, query: str) -> str:
        q = query.lower()

        timezone_map = {
            "tokyo": "Asia/Tokyo",
            "japan": "Asia/Tokyo",
            "delhi": "Asia/Kolkata",
            "india": "Asia/Kolkata",
            "mumbai": "Asia/Kolkata",
            "kolkata": "Asia/Kolkata",
            "london": "Europe/London",
            "uk": "Europe/London",
            "new york": "America/New_York",
            "los angeles": "America/Los_Angeles",
            "san francisco": "America/Los_Angeles",
            "chicago": "America/Chicago",
            "dubai": "Asia/Dubai",
            "singapore": "Asia/Singapore",
            "seoul": "Asia/Seoul",
            "south korea": "Asia/Seoul",
            "sydney": "Australia/Sydney",
            "paris": "Europe/Paris",
            "berlin": "Europe/Berlin",
            "moscow": "Europe/Moscow",
            "beijing": "Asia/Shanghai",
            "china": "Asia/Shanghai",
        }

        for location, timezone in timezone_map.items():
            if location in q:
                return timezone

        return "UTC"

    def _get_active_task_context(self, query: str = ""):

        if not self.task_manager:
            return ""

        task = self.task_manager.switch_task(query)

        if task is None:
            task = self.task_manager.highest_priority_task()

        if not task:
            return ""

        return (
            f"Current Active Task:\n"
            f"Title: {task.title}\n"
            f"Progress: {task.progress:.0f}%\n"
            f"Status: {task.status}\n"
        )

    def _task_reminder(self) -> str:
        if not self.task_manager:
            return ""

        task = self.task_manager.highest_priority_task()

        if not task:
            return ""

        if task.progress >= 100:
            return ""

        return (
            f"\nCurrent unfinished task:\n"
            f"- {task.title}\n"
            f"- Progress: {task.progress:.0f}%\n"
        )

    def _observe_tasks(self, query: str):
        if not self.task_manager:
            return

        query_lower = query.lower()

        project_phrases = [
            "i'm building",
            "i am building",
            "i'm creating",
            "i am creating",
            "i'm making",
            "working on",
            "developing",
            "writing",
            "designing",
        ]

        for phrase in project_phrases:
            if phrase in query_lower:
                subject = query_lower.split(phrase, 1)[1].strip()

                if subject:
                    existing = self.task_manager.switch_task(query)
                    if existing is None:
                        existing = self.task_manager.highest_priority_task()

                    if existing and existing.title.lower() == subject.lower():
                        return

                    self.task_manager.create_task(
                        title=subject.title(),
                        description=f"Long-term task: {subject}"
                    )
                return

    def _update_task_progress(self, query: str):
        if not self.task_manager:
            return

        task = self.task_manager.switch_task(query)
        if task is None:
            task = self.task_manager.highest_priority_task()

        if not task:
            return

        text = query.lower()

        completed_words = [
            "finished",
            "done",
            "completed",
            "implemented",
            "deployed",
            "released",
            "working now",
            "it's working",
        ]

        for word in completed_words:
            if word in text:
                self.task_manager.complete_task(task.id)
                return

        progress_words = [
            "started",
            "implemented",
            "created",
            "added",
            "built",
            "working on",
        ]

        for word in progress_words:
            if word in text:
                progress = min(task.progress + 20.0, 90.0)
                self.task_manager.update_progress(
                    task.id,
                    progress,
                )
                return

    async def process_document(
        self,
        file_path: str,
    ):

        if self.document_pipeline is None:
            return None

        return await self.document_pipeline.process(
            file_path
        )

    async def _retrieve_semantic_memory(
        self,
        query,
    ):
        """
        Retrieve semantic context related to the current query.
        """

        if not self.working_memory:
            return None

        semantic = self.working_memory.semantic()

        logger.info(
            "[SemanticMemory] Retrieved semantic context."
        )

        return {
            "summary": semantic.summary(),
            "graph": semantic,
        }

    async def _execute_required_tools(
        self,
        decision,
        query,
        context,
    ):
        evidence = {}

        for tool in decision.required_tools:

            try:

                if tool == "memory" and self.memory_engine:

                    evidence["memory"] = await self.memory_engine.retrieve(
                        query=query
                    )

                elif tool == "document" and self.document_pipeline:

                    evidence["documents"] = await self.document_pipeline.search(
                        query=query
                    )

                elif tool == "repository" and self.repository_memory:

                    evidence["repository"] = await self.repository_memory.search(
                        query=query
                    )

                elif tool == "study" and self.study_engine:

                    evidence["study"] = await self.study_engine.prepare_context(
                        query=query
                    )

                elif tool == "planner" and self.planner:

                    evidence["plan"] = await self.planner.plan(
                        query=query,
                        context=context,
                    )

                elif tool == "coding" and self.agent_coordinator:

                    evidence["coding"] = await self.agent_coordinator.prepare(
                        "coding",
                        query=query,
                    )

                elif tool == "semantic_memory":

                    evidence["semantic_memory"] = (
                        await self._retrieve_semantic_memory(query)
                    )

            except Exception as e:
                logger.exception(
                    "[Tool Error] %s",
                    tool
                )

                print(
                    f"\n========== {tool.upper()} ERROR =========="
                )
                print(type(e).__name__)
                print(str(e))
                print("=====================================\n")

        return evidence

    def _normalize_execution_verification(
        self,
        evaluation,
        result,
    ) -> Dict[str, Any]:
        """
        Normalize executor verification into one reliable structure.

        Verification states:
        - verified_success
        - verified_failure
        - uncertain
        """

        if not isinstance(evaluation, dict):
            evaluation = {}

        goal_completed = evaluation.get("goal_completed")

        if goal_completed is True:
            return {
                "status": "verified_success",
                "goal_completed": True,
                "confidence": float(
                    evaluation.get("confidence", 1.0)
                    or 1.0
                ),
                "reason": evaluation.get(
                    "reason",
                    "Goal verified successfully.",
                ),
            }

        if goal_completed is False:
            return {
                "status": "verified_failure",
                "goal_completed": False,
                "confidence": float(
                    evaluation.get("confidence", 0.0)
                    or 0.0
                ),
                "reason": evaluation.get(
                    "reason",
                    "Goal was not completed.",
                ),
            }

        # Missing verification is NOT success.
        return {
            "status": "uncertain",
            "goal_completed": False,
            "confidence": 0.0,
            "reason": (
                evaluation.get("reason")
                or "Execution result could not be verified."
            ),
        }

    async def _execute_plan_with_recovery(
        self,
        *,
        plan,
        query: str,
        context: Dict[str, Any],
        max_attempts: int = 3,
    ):
        """
        Execute a plan through a centralized recovery loop.

        Recovery policy:
        1. Execute the current plan.
        2. Verify the result when possible.
        3. Return immediately when the goal is completed.
        4. If execution fails or verification says incomplete,
           attempt intelligent replanning.
        5. Never blindly execute the exact same plan indefinitely.
        """

        current_plan = plan
        last_result = None
        last_error = None

        max_attempts = max(1, min(int(max_attempts), 3))

        for attempt in range(1, max_attempts + 1):

            logger.info(
                "[Recovery] Execution attempt %d/%d for query=%r",
                attempt,
                max_attempts,
                query,
            )

            try:
                if not current_plan:
                    raise ValueError("No executable plan was produced.")

                last_result = await self.executor.execute_plan(
                    current_plan,
                    context,
                )

            except asyncio.TimeoutError:
                last_error = "Executor timed out."

                logger.warning(
                    "[Recovery] Executor timeout on attempt %d/%d.",
                    attempt,
                    max_attempts,
                )

            except Exception as exc:
                last_error = str(exc) or "Executor raised an unknown error."

                logger.exception(
                    "[Recovery] Executor failed on attempt %d/%d: %s",
                    attempt,
                    max_attempts,
                    exc,
                )

            else:
                # -------------------------------------------------
                # VERIFY EXECUTION
                # -------------------------------------------------

                evaluation = None

                if (
                    self.reasoning_engine
                    and hasattr(
                        self.reasoning_engine,
                        "evaluate_result",
                    )
                ):
                    try:
                        evaluation = (
                            await self.reasoning_engine.evaluate_result(
                                query=query,
                                result=last_result,
                            )
                        )

                    except Exception as exc:
                        logger.warning(
                            "[Recovery] Result verification failed: %s",
                            exc,
                        )

                verification = (
                    self._normalize_execution_verification(
                        evaluation,
                        last_result,
                    )
                )

                # -------------------------------------------------
                # ACCEPT VERIFIED SUCCESS
                # -------------------------------------------------

                if verification["goal_completed"]:
                    logger.info(
                        "[Recovery] Goal verified successfully "
                        "on attempt %d.",
                        attempt,
                    )

                    return {
                        "result": last_result,
                        "plan": current_plan,
                        "evaluation": evaluation,
                        "verification": verification,
                        "attempts": attempt,
                        "recovered": attempt > 1,
                        "success": True,
                    }

                # -------------------------------------------------
                # FALLBACK SUCCESS DETECTION
                # -------------------------------------------------

                if isinstance(last_result, dict):

                    explicit_success = last_result.get(
                        "success"
                    )

                    failed_tasks = last_result.get(
                        "failed",
                        [],
                    )

                    skipped_tasks = last_result.get(
                        "skipped",
                        [],
                    )

                    paused = bool(
                        last_result.get(
                            "paused",
                            False,
                        )
                    )

                    if (
                        explicit_success is True
                        and not failed_tasks
                        and not skipped_tasks
                        and not paused
                    ):
                        logger.info(
                            "[Recovery] Executor reported "
                            "successful completion on attempt %d.",
                            attempt,
                        )

                        return {
                            "result": last_result,
                            "plan": current_plan,
                            "evaluation": evaluation,
                            "verification": verification,
                            "attempts": attempt,
                            "recovered": attempt > 1,
                            "success": True,
                        }

                # -------------------------------------------------
                # RECORD FAILURE / INCOMPLETE EXECUTION
                # -------------------------------------------------

                last_error = (
                    "Execution completed but the requested goal "
                    "was not verified."
                )

                if isinstance(evaluation, dict):
                    last_error = (
                        evaluation.get("reason")
                        or evaluation.get("error")
                        or last_error
                    )

            # -----------------------------------------------------
            # NO MORE RECOVERY ATTEMPTS
            # -----------------------------------------------------

            if attempt >= max_attempts:
                break

            # -----------------------------------------------------
            # INTELLIGENT REPLANNING
            # -----------------------------------------------------

            recovery_context = dict(context)

            recovery_context["recovery"] = {
                "attempt": attempt,
                "max_attempts": max_attempts,
                "previous_error": last_error,
                "previous_result": last_result,
            }

            logger.info(
                "[Recovery] Attempting replanning after failed "
                "execution attempt %d.",
                attempt,
            )

            try:

                new_plan = None

                if self.planner and hasattr(
                    self.planner,
                    "plan",
                ):
                    new_plan = await self.planner.plan(
                        query,
                        recovery_context,
                    )

                elif self.planner and hasattr(
                    self.planner,
                    "create_task_graph",
                ):
                    new_plan = self.planner.create_task_graph(
                        query
                    )

                if new_plan is not None:
                    current_plan = new_plan

                    logger.info(
                        "[Recovery] New recovery plan generated "
                        "after attempt %d.",
                        attempt,
                    )

                else:
                    logger.warning(
                        "[Recovery] Planner could not generate "
                        "a recovery plan."
                    )

            except Exception as exc:
                logger.exception(
                    "[Recovery] Replanning failed: %s",
                    exc,
                )

                # If replanning itself fails, preserve the original
                # plan for one controlled retry rather than crashing
                # the entire cognitive pipeline.

        logger.error(
            "[Recovery] Execution failed after %d attempt(s). "
            "Last error: %s",
            max_attempts,
            last_error,
        )

        return {
            "result": last_result,
            "plan": current_plan,
            "evaluation": evaluation if isinstance(evaluation, dict) else {},
            "verification": verification,
            "attempts": max_attempts,
            "recovered": False,
            "success": False,
            "error": last_error,
        }

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
        precomputed_reasoning: Optional[Any] = None,
        completed_goal: Optional[Any] = None,
    ) -> SystemResponse:
        """
        ARIA's core unified cognitive intelligence pipeline orchestrated via Reasoning, Planner, Executor, Memory, WorldModel, Reflection, and Learning.
        """
        if completed_goal:
            response_text = (
                f"Excellent. I've marked "
                f"'{completed_goal.title}' "
                "as completed.\n\n"
                "What would you like to build next?"
            )
            return await self._format_response(response_text, "goal_manager", context, 1.0)

        self.brain_state["retrieving"] = True

        # =========================================================
        # PHASE 1 — CANONICAL COGNITIVE PIPELINE
        # =========================================================
        #
        # This method is the authoritative cognitive path.
        #
        # The pipeline must always follow:
        #
        # INPUT
        #   ↓
        # REFERENCE RESOLUTION
        #   ↓
        # CONTEXT
        #   ↓
        # REASONING
        #   ↓
        # DECISION
        #   ↓
        # EXECUTION / KNOWLEDGE / CHAT
        #   ↓
        # VERIFICATION
        #   ↓
        # RESPONSE
        #
        # Individual routers, agents and tools may assist this
        # pipeline, but none of them may become a second brain.
        # =========================================================

        answer = None
        source = "cognitive_core"
        confidence = 0.0
        decision = None
        execution_result = None
        plan = None

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

        # Step 2: Reuse precomputed reasoning result from process() instead of running reasoning twice
        reasoning = precomputed_reasoning
        if not reasoning and self.reasoning_engine:
            try:
                reasoning = await self.reasoning_engine.reason(context)
            except Exception as e:
                logger.warning("ReasoningEngine invocation skipped: %s", e)

        if reasoning:
            context["reasoning"] = reasoning

        # =========================================================
        # REASONING -> DECISION -> AGENTS -> PLANNER -> EXECUTOR
        # =========================================================

        decision = context.get("decision")
        selected_agents = []
        needs_execution = False

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

        logger.info(
            "[CognitiveCore] Canonical pipeline active: "
            "context -> reasoning -> decision -> execution"
        )

        if decision and decision.use_planner and self.planner and self.executor:
            try:
                if decision.use_planner:

                    plan = await self.planner.plan(
                        resolved_query,
                        context,
                    )

                    recovery = await self._execute_plan_with_recovery(
                        plan=plan,
                        query=resolved_query,
                        context=context,
                        max_attempts=3,
                    )

                    execution_result = recovery.get("result")
                    context["execution_verification"] = (
                        recovery.get("verification", {})
                    )

                    if recovery.get("success"):
                        logger.info(
                            "[CognitiveCore] Planner execution "
                            "completed successfully after %d attempt(s).",
                            recovery.get("attempts", 1),
                        )
                    else:
                        logger.warning(
                            "[CognitiveCore] Planner execution "
                            "could not be verified: %s",
                            recovery.get("error"),
                        )
                else:

                    execution_result = await self.reasoning_engine.reason(
                        resolved_query,
                        context,
                    )
                if isinstance(reasoning, dict):
                    reasoning["execution_result"] = execution_result
                    reasoning["task_plan"] = plan
                elif reasoning is not None:
                    setattr(reasoning, "execution_result", execution_result)
                    setattr(reasoning, "task_plan", plan)
            except Exception as e:
                logger.warning("Planner/Executor execution failed: %s", e)
        elif needs_execution and self.planner and self.executor:
            try:
                plan = self.planner.create_task_graph(resolved_query)
                recovery = await self._execute_plan_with_recovery(
                    plan=plan,
                    query=resolved_query,
                    context=context,
                    max_attempts=3,
                )

                execution_result = recovery.get("result")
                context["execution_verification"] = (
                    recovery.get("verification", {})
                )

                if recovery.get("success"):
                    logger.info(
                        "[CognitiveCore] Task graph execution "
                        "completed successfully after %d attempt(s).",
                        recovery.get("attempts", 1),
                    )
                else:
                    logger.warning(
                        "[CognitiveCore] Task graph execution "
                        "could not be verified: %s",
                        recovery.get("error"),
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
                    recovery = await self._execute_plan_with_recovery(
                        plan=reasoning.plan,
                        query=resolved_query,
                        context=context,
                        max_attempts=3,
                    )

                    result = recovery.get("result")
                    context["execution_verification"] = (
                        recovery.get("verification", {})
                    )

                    if not recovery.get("success"):
                        logger.warning(
                            "[CognitiveCore] Reasoning plan "
                            "execution was not verified: %s",
                            recovery.get("error"),
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
                if decision and decision.use_memory and self.memory_router and hasattr(self.memory_router, "answer"):
                    try:
                        mem_res = await self.memory_router.answer(resolved_query, reasoning_result=reasoning)
                    except Exception as e:
                        logger.warning("Memory router answer search skipped: %s", e)
                elif reasoning and getattr(reasoning, "retrieved_memory", None):
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
                    elif isinstance(mem_res, list):
                        context["memory"] = mem_res
                    else:
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
                    if decision and decision.use_world_model and self.world_model and hasattr(self.world_model, "search"):
                        try:
                            world_res = await asyncio.to_thread(self.world_model.search, resolved_query)
                        except Exception as e:
                            logger.warning("World model search skipped: %s", e)
                    elif reasoning and hasattr(reasoning, "world_state"):
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

                        task_context = self._get_active_task_context(resolved_query)

                        if task_context:
                            system_context += "\n\n" + task_context

                        planning_keywords = [
                            "continue",
                            "next",
                            "roadmap",
                            "plan",
                            "what now",
                            "what next",
                            "resume",
                        ]

                        should_remind = any(
                            word in resolved_query.lower()
                            for word in planning_keywords
                        )

                        if should_remind:
                            reminder = self._task_reminder()
                            if reminder:
                                system_context += "\n" + reminder

                        if execution_result:
                            system_context += f"""

Execution Results:

{execution_result}

"""

                        decision_obj = None
                        if self.working_memory and hasattr(self.working_memory, "metadata"):
                            decision_obj = self.working_memory.metadata.get("cognitive_decision")

                        system_context = self.prompt_builder.build(
                            decision_obj,
                            system_context,
                        )

                        messages = [
                            {
                                "role": "system",
                                "content": system_context
                            }
                        ]

                        memory_items = context.get("memory", [])

                        if memory_items:
                            memory_text = "\n".join(
                                f"{m['key']}: {m['value']}"
                                for m in memory_items
                            )

                            messages.append({
                                "role": "system",
                                "content":
                                    "Known user memories:\n"
                                    + memory_text +
                                    "\nUse these memories when answering if relevant."
                            })

                        messages.append({
                            "role": "user",
                            "content": resolved_query
                        })
                        reply = await self.llm_router.chat(messages)
                        if isinstance(reply, dict) and not reply.get("success", True):
                            answer = None
                        else:
                            answer = str(reply).strip() if reply else None

                        source = "llm_generated"
                        confidence = 0.70
                    except Exception as e:
                        logger.warning("LLM fallback generation skipped: %s", e)

                if not answer:
                    class DummyExecutionResults:
                        def __init__(self, completed):
                            self.completed = completed
                    
                    verification = context.get(
                        "execution_verification",
                        {},
                    )

                    verification_status = verification.get(
                        "status"
                    )

                    if (
                        execution_result
                        and verification_status == "verified_success"
                    ):
                        execution_results = DummyExecutionResults(
                            execution_result.get("completed", [])
                            if isinstance(execution_result, dict)
                            else []
                        )

                        if execution_results.completed:
                            answer = execution_results.completed[-1]

                    elif (
                        execution_result
                        and verification_status == "uncertain"
                    ):
                        answer = (
                            "I completed the execution attempt, "
                            "but I could not reliably verify that the "
                            "requested result was achieved."
                        )

                    if not answer:
                        answer = (
                            "I'm temporarily unable to reach my language models. "
                            "Please try again in a few seconds."
                        )
                    confidence = 0.1

        finally:
            self.brain_state["retrieving"] = False
            self.brain_state["thinking"] = False
            self.brain_state["reasoning"] = False

        # Step 6: Reflection and Learning hooks before returning
        if self.self_reflection:
            try:
                await self.self_reflection.reflect(
                    "review",
                    query=resolved_query,
                    answer=answer,
                    source=source,
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

    def _looks_like_memory_recall_request(self, query: str) -> bool:
        """
        Detect questions that ask ARIA to retrieve existing memories
        rather than store/update a new memory.
        """

        q = str(query or "").strip().lower()

        recall_phrases = (
            "what do you remember about me",
            "what do you remember about me?",
            "what do you know about me",
            "what do you know about me?",
            "what can you remember about me",
            "what can you remember about me?",
            "tell me what you remember about me",
            "tell me what you know about me",
            "show me what you remember about me",
            "show me what you know about me",
            "list what you remember about me",
            "list what you know about me",
            "what have you remembered about me",
            "what have you learned about me",
            "what memories do you have about me",
            "show my memories",
            "list my memories",
        )

        return any(
            phrase in q
            for phrase in recall_phrases
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
            # PHASE 1 — FAST ROUTER AS CLASSIFIER ONLY
            # =================================================
            #
            # FastRouter is allowed to classify the request for
            # performance, but it is NOT allowed to generate the
            # final response or bypass the Cognitive Core.
            #
            # Canonical ownership remains:
            #
            # CognitiveCore
            #     ↓
            # routing classification
            #     ↓
            # authoritative decision
            #     ↓
            # execution / reasoning / knowledge / memory / LLM
            #
            # This prevents FastRouter from becoming a second brain.
            # =================================================

            fast_decision = None

            try:
                fast_decision = should_fast_route(query)

                if fast_decision:
                    logger.info(
                        "[FastRouter] Classification=%s reason=%s",
                        getattr(fast_decision, "fast", False),
                        getattr(fast_decision, "reason", "unknown"),
                    )

            except Exception as e:
                logger.warning(
                    "[FastRouter] Classification skipped: %s",
                    e,
                )

            # IMPORTANT:
            # Do not return from the FastRouter.
            # The request must continue through the canonical
            # Cognitive Core pipeline.


            # ============================================
            # MEMORY RECALL FAST PATH
            # ============================================
            #
            # Questions asking what ARIA already remembers
            # must NEVER be routed to memory storage.
            #
            # Example:
            #   "What do you remember about me?"
            #
            # This is retrieval, not memory creation.
            # ============================================

            if self._looks_like_memory_recall_request(query):

                logger.info(
                    "[MemoryRecall] Retrieving existing memories."
                )

                try:
                    memories = await self.memory_engine.retrieve(query)

                    if memories:
                        return SystemResponse(
                            success=True,
                            confidence=1.0,
                            source="memory",
                            data={
                                "memories": memories,
                            },
                        )

                    return SystemResponse(
                        success=True,
                        confidence=1.0,
                        source="memory",
                        data={
                            "memories": [],
                            "message": "I don't have any relevant memories about you yet, Sir.",
                        },
                    )

                except Exception as e:
                    logger.exception(
                        "[MemoryRecall] Memory retrieval failed: %s",
                        e,
                    )

                    return SystemResponse(
                        success=False,
                        confidence=0.0,
                        source="memory",
                        error="I couldn't retrieve your memories right now.",
                    )


            # ============================================
            # EXECUTION ROUTER
            # ============================================

            route = decide(query)

            logger.info(
                "[ExecutionRouter] Route=%s Confidence=%.2f",
                route.route.value,
                route.confidence,
            )

            if route.route == Route.MEMORY:
                await self.memory_engine.deterministic_extract_and_store(query)

                return SystemResponse(
                    success=True,
                    confidence=1.0,
                    source="memory",
                    data={
                        "response": "Certainly, Sir. I'll remember that.",
                        "message": "Certainly, Sir. I'll remember that.",
                    },
                )

            if route.route == Route.GREETING:
                return SystemResponse(
                    success=True,
                    confidence=1.0,
                    source="execution_router",
                    data={
                        "response": "Hello, Sir. How can I help you today?",
                        "message": "Hello, Sir. How can I help you today?",
                    },
                )

            if route.route == Route.TIME:
                try:
                    timezone = self._extract_timezone(query)

                    if not self.action_manager:
                        return SystemResponse(
                            success=False,
                            confidence=1.0,
                            source="time_action",
                            error="Time action manager is not available.",
                        )

                    action_result = await self.action_manager.execute_action(
                        action_name="time_action",
                        params={
                            "timezone": timezone,
                        },
                        confirmed=True,
                    )

                    if not action_result.success:
                        return SystemResponse(
                            success=False,
                            confidence=1.0,
                            source="time_action",
                            error=action_result.error,
                        )

                    data = action_result.data or {}

                    return SystemResponse(
                        success=True,
                        confidence=1.0,
                        source="time_action",
                        data={
                            "timezone": data.get("timezone"),
                            "date": data.get("date"),
                            "time": data.get("time"),
                            "utc_offset": data.get("utc_offset"),
                            "message": (
                                f"The current time in {data.get('timezone')} "
                                f"is {data.get('time')}."
                            ),
                        },
                    )

                except Exception as e:
                    logger.exception(
                        "[TimeAction] Time retrieval failed: %s",
                        e,
                    )

                    return SystemResponse(
                        success=False,
                        confidence=0.0,
                        source="time_action",
                        error=f"Unable to retrieve time: {e}",
                    )

            if route.route == Route.WEATHER:
                try:

                    if not self.action_manager:
                        return SystemResponse(
                            success=False,
                            confidence=1.0,
                            source="weather_action",
                            error="Weather action manager is not available.",
                        )

                    # -------------------------------------------------
                    # Extract structured weather parameters
                    # -------------------------------------------------

                    weather_params = self._extract_weather_params(query)

                    logger.info(
                        "[WeatherRoute] location=%s | forecast_days=%s | target=%s",
                        weather_params.get("location"),
                        weather_params.get("forecast_days"),
                        weather_params.get("forecast_target"),
                    )

                    action_result = await self.action_manager.execute_action(
                        action_name="weather_action",
                        params=weather_params,
                        confirmed=True,
                    )

                    if not action_result.success:
                        return SystemResponse(
                            success=False,
                            confidence=1.0,
                            source="weather_action",
                            error=action_result.error,
                        )

                    data = action_result.data or {}

                    return SystemResponse(
                        success=True,
                        confidence=1.0,
                        source="weather_action",
                        data={
                            "response": data.get("message"),
                            "message": data.get("message"),
                            "location": data.get("location"),
                            "city": data.get("city"),
                            "country": data.get("country"),
                            "country_code": data.get("country_code"),
                            "latitude": data.get("latitude"),
                            "longitude": data.get("longitude"),
                            "timezone": data.get("timezone"),
                            "current": data.get("current"),
                            "forecast": data.get("forecast"),
                            "forecast_target": weather_params.get(
                                "forecast_target"
                            ),
                        },
                    )

                except Exception as e:
                    logger.exception(
                        "[WeatherAction] Weather retrieval failed: %s",
                        e,
                    )

                    return SystemResponse(
                        success=False,
                        confidence=0.0,
                        source="weather_action",
                        error=f"Unable to retrieve weather: {e}",
                    )

            if route.route == Route.CODING:

                engine = self.engine_manager.get("coding")

                reply = await engine.process(query)

                return SystemResponse(
                    success=True,
                    confidence=1.0,
                    source="coding_engine",
                    data={
                        "response": reply,
                        "message": reply,
                    },
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
            # 1.5 INITIALIZE UNIFIED EXECUTION CONTEXT
            # =================================================
            context = dict(base_context or {})
            context.update({
                # Core identity / request
                "query": query,
                "session_id": session_id,
                "user_id": user_id,

                # Cognitive state
                "state": state,

                # Brain components
                "memory": self.memory_engine,
                "planner": self.planner,
                "executor": self.executor,
                "reasoning": self.reasoning_engine,
                "decision": self.decision_engine,

                # Capability managers
                "agent_manager": getattr(self, "agent_manager", None),
                "tool_manager": getattr(self, "tool_manager", None),
                "action_manager": self.action_manager,
                "skill_manager": self.skill_manager,

                # Conversation
                "conversation_manager": self.conversation_manager,
                "working_memory": self.working_memory,

                # Knowledge
                "knowledge_manager": self.knowledge_manager,
                "knowledge_graph": self.knowledge_graph,
                "knowledge_database": self.knowledge_database,
                "world_model": self.world_model,

                # Learning / reflection
                "learning_engine": self.learning_engine,
                "autonomous_learning": self.autonomous_learning,
                "self_reflection": self.self_reflection,

                # Routing metadata
                "fast_route": (
                    getattr(fast_decision, "reason", None)
                    if fast_decision
                    else None
                ),
            })

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
            # 2.5 COGNITIVE CONTROLLER ANALYSIS & CONTROLLED RETRIEVAL
            # =================================================
            context.update({
                "session_id": session_id,
                "user_id": user_id,
                "state": state,
                "base_context": base_context,
                "context": context,
            })
            
            # Initial cognitive analysis
            controller_decision = self.cognitive_controller.analyze(
                query=query,
                context=context,
            )

            context["cognitive_decision"] = controller_decision

            # =============================================================
            # 2.6 NORMALIZE COGNITIVE DECISION
            # =============================================================

            def _decision_value(decision, key, default=None):
                if decision is None:
                    return default

                if isinstance(decision, dict):
                    return decision.get(key, default)

                return getattr(decision, key, default)


            decision_contract = {
                "intent": _decision_value(
                    controller_decision,
                    "intent",
                ),
                "route": _decision_value(
                    controller_decision,
                    "route",
                ),
                "action": _decision_value(
                    controller_decision,
                    "action",
                ),
                "requires_reasoning": bool(
                    _decision_value(
                        controller_decision,
                        "requires_reasoning",
                        False,
                    )
                ),
                "requires_memory": bool(
                    _decision_value(
                        controller_decision,
                        "requires_memory",
                        False,
                    )
                ),
                "requires_tool": bool(
                    _decision_value(
                        controller_decision,
                        "requires_tool",
                        False,
                    )
                ),
                "requires_planning": bool(
                    _decision_value(
                        controller_decision,
                        "requires_planning",
                        False,
                    )
                ),
                "confidence": _decision_value(
                    controller_decision,
                    "confidence",
                ),
            }

            context["decision_contract"] = decision_contract

            logger.info(
                "[CognitiveDecision] Normalized decision: %s",
                decision_contract,
            )

            logger.info(
                "[CognitiveController] %s",
                controller_decision,
            )

            if self.working_memory:
                if hasattr(self.working_memory, "metadata"):
                    self.working_memory.metadata["required_tools"] = (
                        controller_decision.required_tools
                    )
                else:
                    setattr(self.working_memory, "required_tools", controller_decision.required_tools)

            if self.working_memory:
                if hasattr(self.working_memory, "metadata"):
                    self.working_memory.metadata["cognitive_decision"] = controller_decision
                else:
                    setattr(self.working_memory, "cognitive_decision", controller_decision)

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
            # 4.5 OBSERVE & UPDATE TASKS
            # =================================================
            self._observe_tasks(query)
            self._update_task_progress(query)

            # =================================================
            # 5. INTENT ANALYSIS
            # =================================================

            intent = None

            if self.intent_analyzer:

                try:
                    intent = (
                        await self.intent_analyzer.analyze(query)
                    )

                except Exception:
                    logger.exception(
                        "[CognitiveCore] Intent analysis failed."
                    )

            # =================================================
            # 6. DECISION ENGINE INTEGRATION (Central Control)
            # =================================================
            pre_ctx = dict(context)
            pre_ctx["query"] = query
            pre_ctx["session_id"] = session_id
            pre_ctx["user_id"] = user_id
            pre_ctx["state"] = state
            if intent:
                pre_ctx["intent"] = intent

            decision = controller_decision
            if self.decision_engine and hasattr(self.decision_engine, "decide"):

                engine_decision = await self.decision_engine.decide(
                    query=query,
                    intent=intent,
                    context=pre_ctx,
                )

                if engine_decision:
                    decision = engine_decision

            logger.info(
                "[CognitiveCore] Using decision: %s",
                decision,
            )

            pre_ctx["decision"] = decision
            context["decision"] = decision

            # Execute required tools based on final decision
            evidence = await self._execute_required_tools(
                decision,
                query,
                context,
            )

            if self.working_memory:
                if hasattr(self.working_memory, "metadata"):
                    self.working_memory.metadata["tool_results"] = evidence
                else:
                    setattr(self.working_memory, "tool_results", evidence)

            if "semantic_memory" in evidence:

                self.working_memory.metadata[
                    "semantic_context"
                ] = evidence["semantic_memory"]

            logger.info(
                "[CognitiveController] Executed Tools: %s",
                list(evidence.keys()),
            )

            reasoning = None
            if self.reasoning_engine and hasattr(self.reasoning_engine, "reason"):
                try:
                    reasoning = await self.reasoning_engine.reason(context)
                except Exception:
                    logger.exception("[CognitiveCore] Initial ReasoningEngine invocation failed.")

            # =================================================
            # PHASE 9: GOAL MANAGER & PROJECT MANAGER HOOKS
            # =================================================

            completed_goal = None

            if self.goal_manager:
                try:
                    active_before = self.goal_manager.current_goal()

                    await self.goal_manager.observe(query, pre_ctx)

                    active_after = self.goal_manager.current_goal()

                    if active_before and active_after is None:
                        completed_goal = active_before
                except Exception:
                    logger.exception("[CognitiveCore] GoalManager observation failed.")

            if self.project_manager:
                try:
                    await self.project_manager.observe(query, pre_ctx)
                except Exception:
                    logger.exception("[CognitiveCore] ProjectManager observation failed.")

            # =================================================
            # 7. RETRIEVE RELEVANT MEMORY CONDITIONALLY VIA ROUTER / ENGINE
            # =================================================

            memories = evidence.get("memory", [])

            if not memories:
                if decision and decision.use_memory:
                    if self.memory_engine:
                        try:
                            memories = await self.memory_engine.retrieve(query) or []
                        except Exception:
                            logger.exception("[CognitiveCore] Memory engine retrieval failed.")
                    elif self.memory_router:
                        try:
                            memories = (
                                await self.memory_router.recall(query)
                            ) or []
                        except Exception:
                            logger.exception(
                                "[CognitiveCore] Memory retrieval failed."
                            )
                elif self.memory_engine and reasoning and getattr(reasoning, "requires_memory", False):
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
            # 8. BUILD COMPLETE CONTEXT
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
                context.update(ctx)

            else:
                context["query"] = query
                context["session_id"] = session_id
                context["user_id"] = user_id
                context["state"] = state
                context["memory"] = memories

            context.setdefault("query", query)
            context.setdefault("session_id", session_id)
            context.setdefault("user_id", user_id)
            context.setdefault("state", state)
            context.setdefault("memory", memories)

            if intent:
                context["intent"] = intent

            if decision:
                context["decision"] = decision

            # =================================================
            # 9. ATTACH REGISTERED CAPABILITIES
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

            context["document_intelligence"] = document_ai
            context["document_repository"] = document_repository

            context["capabilities"] = {
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
            # 10. SAVE CURRENT QUERY
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
                        context=context,
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
                                context["memory"] = refreshed

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
                context,
                precomputed_reasoning=reasoning,
                completed_goal=completed_goal,
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
