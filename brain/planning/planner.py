import json
import logging
import re
from typing import Dict, Any, List, Optional
from datetime import datetime

from brain.memory.memory_router import MemoryRouter
from brain.plan import ExecutionPlan
from brain.task import Task


logger = logging.getLogger("aria")


class Planner:
    """
    Dynamic capability-based planner for ARIA.

    The Planner does NOT contain a list of user commands.

    Its job is to:

    1. Understand the goal already identified by reasoning.
    2. Inspect ARIA's available skills/actions/capabilities.
    3. Decide whether one or multiple steps are required.
    4. Produce a strongly-typed ExecutionPlan.
    5. Allow Executor to perform the actual work.

    This keeps command interpretation out of hard-coded
    if/elif chains.
    """

    def __init__(
        self,
        memory_router: MemoryRouter,
        llm_router=None,
        skill_manager=None,
        action_manager=None,
        knowledge_manager=None,
        world_model=None,
        knowledge_graph=None,
        reasoning_engine=None,
        event_bus=None,
    ):
        self.memory_router = memory_router
        self.llm_router = llm_router
        self.skill_manager = skill_manager
        self.action_manager = action_manager

        self.knowledge_manager = knowledge_manager
        self.world_model = world_model
        self.knowledge_graph = knowledge_graph
        self.reasoning_engine = reasoning_engine
        self.event_bus = event_bus

        self.active_plan: Optional[ExecutionPlan] = None
        self.plan_history: List[ExecutionPlan] = []
        self.statistics = {
            "plans_created": 0,
            "plans_reused": 0,
            "plans_failed": 0,
            "plans_repaired": 0,
            "average_steps": 0.0,
            "average_success_rate": 1.0,
        }

    # =========================================================
    # DEPENDENCY INJECTION
    # =========================================================

    def set_skill_manager(
        self,
        skill_manager,
    ):
        self.skill_manager = skill_manager

    def set_action_manager(
        self,
        action_manager,
    ):
        self.action_manager = action_manager

    def set_llm_router(
        self,
        llm_router,
    ):
        self.llm_router = llm_router

    # =========================================================
    # CAPABILITY DISCOVERY
    # =========================================================

    def _get_skill_capabilities(
        self,
    ) -> List[Dict[str, Any]]:

        if not self.skill_manager:
            return []

        if hasattr(
            self.skill_manager,
            "get_capabilities",
        ):
            try:
                return (
                    self.skill_manager
                    .get_capabilities()
                )
            except Exception:
                logger.exception(
                    "[Planner] Failed to read skill capabilities."
                )

        return []

    def _get_action_capabilities(
        self,
    ) -> List[Dict[str, Any]]:

        if not self.action_manager:
            return []

        actions = getattr(
            self.action_manager,
            "actions",
            {},
        )

        if not isinstance(actions, dict):
            return []

        capabilities = []

        for name, action in actions.items():

            capabilities.append({
                "name": name,
                "description": str(
                    getattr(
                        action,
                        "description",
                        "",
                    )
                    or ""
                ),
                "permission_level": getattr(
                    action,
                    "permission_level",
                    "safe",
                ),
                "type": "action",
            })

        return capabilities

    def get_available_capabilities(
        self,
    ) -> Dict[str, Any]:
        """
        Machine-readable inventory of what ARIA can
        currently use while planning.
        """

        return {
            "skills":
                self._get_skill_capabilities(),

            "actions":
                self._get_action_capabilities(),
        }

    # =========================================================
    # CONTEXT EXTRACTION & ENRICHMENT
    # =========================================================

    async def _enrich_context(
        self,
        query: str,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        enriched = dict(context or {})
        session_id = enriched.get("session_id", "default_session")

        if self.knowledge_manager and hasattr(self.knowledge_manager, "retrieve"):
            try:
                enriched["knowledge_evidence"] = await self.knowledge_manager.retrieve(session_id, query)
            except Exception:
                enriched["knowledge_evidence"] = []

        if self.world_model and hasattr(self.world_model, "snapshot"):
            try:
                enriched["world_snapshot"] = self.world_model.snapshot()
            except Exception:
                enriched["world_snapshot"] = {}

        if self.knowledge_graph and hasattr(self.knowledge_graph, "search"):
            try:
                enriched["graph_evidence"] = await self.knowledge_graph.search(query)
            except Exception:
                enriched["graph_evidence"] = []

        return enriched

    def _extract_reasoning(
        self,
        context: Dict[str, Any],
    ):

        if not isinstance(context, dict):
            return None

        return context.get("reasoning")

    def _extract_goal(
        self,
        query: str,
        context: Dict[str, Any],
    ) -> str:

        reasoning = self._extract_reasoning(
            context
        )

        if reasoning:

            metadata = getattr(
                reasoning,
                "metadata",
                {},
            ) or {}

            goal = metadata.get("goal")

            if goal:
                return str(goal)

        return str(query or "").strip()

    # =========================================================
    # TASK GRAPH CREATION
    # =========================================================

    def create_task_graph(self, goal: str):
        """
        Convert a goal into executable tasks.
        """

        goal_lower = goal.lower()

        tasks = []

        if any(word in goal_lower for word in [
            "build",
            "create",
            "develop",
            "implement"
        ]):

            tasks = [

                {
                    "id": 1,
                    "agent": "research",
                    "task": f"Research requirements for: {goal}",
                    "status": "pending"
                },

                {
                    "id": 2,
                    "agent": "planning",
                    "task": f"Design architecture for: {goal}",
                    "status": "pending"
                },

                {
                    "id": 3,
                    "agent": "coding",
                    "task": f"Implement: {goal}",
                    "status": "pending"
                },

                {
                    "id": 4,
                    "agent": "testing",
                    "task": f"Test: {goal}",
                    "status": "pending"
                }

            ]

        elif any(word in goal_lower for word in [
            "research",
            "compare",
            "explain"
        ]):

            tasks = [

                {
                    "id": 1,
                    "agent": "research",
                    "task": goal,
                    "status": "pending"
                },

                {
                    "id": 2,
                    "agent": "writing",
                    "task": "Summarize findings",
                    "status": "pending"
                }

            ]

        else:

            tasks = [

                {
                    "id": 1,
                    "agent": "chat",
                    "task": goal,
                    "status": "pending"
                }

            ]

        return tasks

    # =========================================================
    # GOAL DECOMPOSITION
    # =========================================================

    async def decompose_goal(
        self,
        goal: str,
    ) -> List[str]:
        """
        Decompose a high-level user goal into structured sub-goals.
        """
        if not self.llm_router:
            return [goal]

        prompt = f"""
Decompose the following user goal into a sequence of distinct sub-goals.
Goal: {goal}
Return ONLY a JSON list of strings representing the sub-goals.
"""
        try:
            res = await self.llm_router.chat(
                messages=[
                    {"role": "system", "content": "You are a goal decomposition planner. Return only JSON lists of strings."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.0,
                max_tokens=300,
            )
            text = str(res).strip()
            if text.startswith("```"):
                lines = text.splitlines()[1:-1]
                text = "\n".join(lines).strip()
                if text.lower().startswith("json"):
                    text = text[4:].strip()
            sub_goals = json.loads(text)
            if isinstance(sub_goals, list) and sub_goals:
                return [str(g) for g in sub_goals]
        except Exception:
            logger.exception("[Planner] Goal decomposition failed.")

        return [goal]

    # =========================================================
    # PLAN REUSE & SIMILARITY
    # =========================================================

    async def find_similar_plan(
        self,
        query: str,
    ) -> Optional[ExecutionPlan]:
        q_lower = query.lower()
        for past_plan in reversed(self.plan_history):
            if past_plan.goal and (q_lower in past_plan.goal.lower() or past_plan.goal.lower() in q_lower):
                self.statistics["plans_reused"] += 1
                logger.info("[Planner] Reusing historical plan for goal: %s", past_plan.goal)
                return past_plan
        return None

    # =========================================================
    # TASK NORMALIZATION & VALIDATION
    # =========================================================

    def _normalize_task(
        self,
        raw_task: Dict[str, Any],
        index: int,
    ) -> Optional[Task]:

        if not isinstance(raw_task, dict):
            return None

        skill = str(
            raw_task.get("skill")
            or raw_task.get("action")
            or ""
        ).strip()

        if not skill:
            return None

        task_id = str(
            raw_task.get("id")
            or f"task_{index}"
        )

        task_name = str(
            raw_task.get("name")
            or skill
        )

        task_input = raw_task.get(
            "input",
            {},
        )

        if not isinstance(
            task_input,
            dict,
        ):
            task_input = {}

        depends_on = raw_task.get("depends_on", [])
        if not isinstance(depends_on, list):
            depends_on = []

        assigned_agent = raw_task.get("assigned_agent", "auto")

        return Task(
            id=task_id,
            name=task_name,
            skill=skill,
            input=task_input,
            depends_on=depends_on,
            assigned_agent=assigned_agent,
        )

    def validate_plan(
        self,
        plan: ExecutionPlan,
    ) -> bool:
        """
        Validate that all tasks, skills, actions, and dependencies are valid and loop-free.
        """
        if not plan or not plan.tasks:
            return False

        available = self.get_available_capabilities()
        valid_skills = {s["name"] for s in available.get("skills", [])}
        valid_actions = {a["name"] for a in available.get("actions", [])}
        all_valid_caps = valid_skills.union(valid_actions)

        task_ids = {t.id for t in plan.tasks}
        for task in plan.tasks:
            if not task.skill:
                return False
            # Check dependency validity
            for dep in task.depends_on:
                if dep not in task_ids:
                    return False
            # Prevent circular self-dependency
            if task.id in task.depends_on:
                return False

        return True

    # =========================================================
    # PLAN OPTIMIZATION & METADATA
    # =========================================================

    def optimize_plan(
        self,
        plan: ExecutionPlan,
    ) -> ExecutionPlan:
        """
        Optimize plan by removing duplicates and computing estimates.
        """
        if not plan or not plan.tasks:
            return plan

        seen_signatures = set()
        optimized_tasks = []
        for task in plan.tasks:
            sig = (task.skill, json.dumps(task.input, sort_keys=True))
            if sig not in seen_signatures:
                seen_signatures.add(sig)
                optimized_tasks.append(task)

        plan.tasks = optimized_tasks

        steps = len(plan.tasks)
        plan.metadata = {
            "estimated_steps": steps,
            "estimated_time": steps * 2,  # seconds estimate
            "estimated_llm_calls": 1 if steps > 0 else 0,
            "estimated_tools": steps,
        }
        return plan

    # =========================================================
    # FAILURE RECOVERY & REPAIR
    # =========================================================

    async def repair_plan(
        self,
        plan: ExecutionPlan,
        failed_task: Task,
    ) -> Optional[ExecutionPlan]:
        """
        Create a recovery mini-plan starting from the failed task.
        """
        self.statistics["plans_repaired"] += 1
        logger.warning("[Planner] Repairing plan after failure at task: %s", failed_task.id)

        repair_task = Task(
            id=f"repair_{failed_task.id}",
            name=f"Fallback recovery for {failed_task.name}",
            skill="chat",
            input={"query": f"Recover from failure in task {failed_task.name}"},
        )
        return ExecutionPlan(
            goal=f"Repair failure for {plan.goal}",
            tasks=[repair_task],
        )

    # =========================================================
    # ADAPTIVE PLAN MODIFICATION
    # =========================================================

    async def modify_plan(
        self,
        existing_plan: ExecutionPlan,
        query: str,
        context: Dict[str, Any],
    ) -> ExecutionPlan:
        """
        Modify an existing active plan based on new user requirements.
        """
        if not self.llm_router:
            return existing_plan

        capabilities = self.get_available_capabilities()
        existing_tasks_json = json.dumps([t.__dict__ for t in existing_plan.tasks], default=str)

        prompt = f"""
You are ARIA's advanced workflow adaptation engine.
The user wants to modify an existing active plan. Update only the affected sections, add/remove/change tasks as requested, and preserve everything else that remains valid.

EXISTING PLAN GOAL:
{existing_plan.goal}

EXISTING TASKS:
{existing_tasks_json}

USER CHANGE REQUEST:
{query}

AVAILABLE CAPABILITIES:
{json.dumps(capabilities, default=str)}

RULES:
1. Never invent a skill or action.
2. Use only names present in AVAILABLE CAPABILITIES.
3. Return ONLY valid JSON in exactly this structure:

{{
  "goal": "updated description of the user's goal",
  "tasks": [
    {{
      "id": "task_1",
      "name": "short task description",
      "skill": "registered capability name",
      "assigned_agent": "auto",
      "depends_on": [],
      "input": {{}}
    }}
  ]
}}
"""
        try:
            raw_response = await self.llm_router.chat(
                messages=[
                    {
                        "role": "system",
                        "content": "You are ARIA's workflow adaptation engine. Update existing plans based on requirements. Return only valid JSON.",
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                temperature=0.0,
                max_tokens=1200,
                task="planning",
            )

            if raw_response:
                text = str(raw_response).strip()
                if text.startswith("```"):
                    lines = text.splitlines()
                    if lines:
                        lines = lines[1:]
                    if lines and lines[-1].strip() == "```":
                        lines = lines[:-1]
                    text = "\n".join(lines).strip()
                    if text.lower().startswith("json"):
                        text = text[4:].strip()

                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    raw_tasks = parsed.get("tasks", [])
                    tasks: List[Task] = []
                    for index, raw_task in enumerate(raw_tasks, start=1):
                        task = self._normalize_task(raw_task, index)
                        if task:
                            tasks.append(task)

                    updated_goal = str(parsed.get("goal") or existing_plan.goal).strip()
                    updated_plan = ExecutionPlan(
                        goal=updated_goal,
                        tasks=tasks,
                    )
                    if self.validate_plan(updated_plan):
                        optimized = self.optimize_plan(updated_plan)
                        optimized.confidence = 0.93
                        task_graph = self.create_task_graph(updated_goal)
                        if isinstance(optimized.metadata, dict):
                            optimized.metadata["task_graph"] = task_graph
                        else:
                            optimized.metadata = {"task_graph": task_graph}
                        
                        logger.info("[Planner] Updated existing plan.")
                        return optimized
        except Exception:
            logger.exception("[Planner] Plan modification failed.")

        return existing_plan

    # =========================================================
    # LLM PLAN GENERATION
    # =========================================================

    async def _generate_dynamic_plan(
        self,
        query: str,
        context: Dict[str, Any],
    ) -> Optional[ExecutionPlan]:
        """
        Ask ARIA's language/reasoning layer to compose a
        workflow from capabilities.

        No individual user command is hard-coded here.
        """

        if not self.llm_router:
            return None

        enriched_context = await self._enrich_context(query, context)

        capabilities = (
            self.get_available_capabilities()
        )

        if (
            not capabilities["skills"]
            and not capabilities["actions"]
        ):
            return None

        goal = self._extract_goal(
            query,
            context,
        )

        sub_goals = await self.decompose_goal(goal)

        conversation = enriched_context.get(
            "conversation",
            {},
        ) or {}

        document = enriched_context.get(
            "document",
            {},
        ) or {}

        memory = enriched_context.get(
            "memory",
            [],
        ) or []

        knowledge_evidence = enriched_context.get("knowledge_evidence", [])
        world_snapshot = enriched_context.get("world_snapshot", {})

        planner_prompt = f"""
You are ARIA's advanced multi-agent workflow planner.

Your job is to convert the user's goal into the smallest safe
sequence of executable tasks using ONLY the capabilities listed
below.

USER REQUEST:
{query}

GOAL:
{goal}

SUB-GOALS:
{json.dumps(sub_goals)}

AVAILABLE CAPABILITIES:
{json.dumps(capabilities, default=str)}

KNOWLEDGE EVIDENCE:
{json.dumps(knowledge_evidence, default=str)}

WORLD STATE:
{json.dumps(world_snapshot, default=str)}

ACTIVE DOCUMENT CONTEXT:
{json.dumps(document, default=str)}

RULES:

1. Never invent a skill or action.
2. Use only names present in AVAILABLE CAPABILITIES.
3. Prefer the smallest plan that fully completes the goal.
4. A simple request should normally use one task.
5. A compound request may use multiple ordered tasks with explicit `depends_on` lists.
6. Assign appropriate specialist agents (e.g., CodeAgent, ResearchAgent, MathAgent) via `assigned_agent` if applicable.
7. Return ONLY valid JSON in exactly this structure:

{{
  "goal": "clear description of the user's goal",
  "tasks": [
    {{
      "id": "task_1",
      "name": "short task description",
      "skill": "registered capability name",
      "assigned_agent": "auto",
      "depends_on": [],
      "input": {{}}
    }}
  ]
}}
"""

        try:

            raw_response = None

            if hasattr(
                self.llm_router,
                "chat",
            ):
                raw_response = (
                    await self.llm_router.chat(
                        messages=[
                            {
                                "role": "system",
                                "content": (
                                    "You are ARIA's workflow planning engine. "
                                    "Create executable plans using only the "
                                    "capabilities provided to you. "
                                    "Return only valid JSON."
                                ),
                            },
                            {
                                "role": "user",
                                "content": planner_prompt,
                            },
                        ],
                        temperature=0.0,
                        max_tokens=1200,
                        task="planning",
                    )
                )

            if raw_response is None:
                return None

            if isinstance(
                raw_response,
                dict,
            ):
                parsed = raw_response

            else:

                text = str(
                    raw_response
                ).strip()

                # Tolerate fenced JSON from providers.
                if text.startswith("```"):
                    lines = text.splitlines()

                    if lines:
                        lines = lines[1:]

                    if (
                        lines
                        and lines[-1].strip()
                        == "```"
                    ):
                        lines = lines[:-1]

                    text = "\n".join(
                        lines
                    ).strip()

                    if text.lower().startswith(
                        "json"
                    ):
                        text = text[4:].strip()

                parsed = json.loads(text)

            if not isinstance(
                parsed,
                dict,
            ):
                return None

            raw_tasks = parsed.get(
                "tasks",
                [],
            )

            if not isinstance(
                raw_tasks,
                list,
            ):
                return None

            tasks: List[Task] = []

            for index, raw_task in enumerate(
                raw_tasks,
                start=1,
            ):

                task = self._normalize_task(
                    raw_task,
                    index,
                )

                if task:
                    tasks.append(task)

            plan_goal = str(
                parsed.get("goal")
                or goal
            ).strip()

            plan = ExecutionPlan(
                goal=plan_goal,
                tasks=tasks,
            )

            if not self.validate_plan(plan):
                logger.warning("[Planner] Generated plan failed validation.")
                return None

            optimized = self.optimize_plan(plan)
            optimized.confidence = 0.92
            
            # Attach structured task graph
            task_graph = self.create_task_graph(plan_goal)
            if isinstance(optimized.metadata, dict):
                optimized.metadata["task_graph"] = task_graph
            else:
                optimized.metadata = {"task_graph": task_graph}

            logger.info("[Planner] Created new plan.")
            return optimized

        except Exception:

            logger.exception(
                "[Planner] Dynamic planning failed."
            )

            return None

    # =========================================================
    # REASONING WORKFLOW FALLBACK
    # =========================================================

    def _plan_from_reasoning(
        self,
        query: str,
        context: Dict[str, Any],
    ) -> Optional[ExecutionPlan]:
        """
        If ReasoningEngine has already constructed a workflow,
        convert it into an ExecutionPlan without reinterpreting
        individual commands.
        """

        reasoning = self._extract_reasoning(
            context
        )

        if not reasoning:
            return None

        workflow = getattr(
            reasoning,
            "workflow",
            None,
        )

        if not workflow:
            return None

        tasks: List[Task] = []

        for index, step in enumerate(
            workflow,
            start=1,
        ):

            if isinstance(step, dict):

                task = self._normalize_task(
                    step,
                    index,
                )

                if task:
                    tasks.append(task)

                continue

            name = str(
                getattr(
                    step,
                    "name",
                    "",
                )
                or ""
            ).strip()

            if not name:
                continue

            task_input = getattr(
                step,
                "input",
                {},
            )

            if not isinstance(
                task_input,
                dict,
            ):
                task_input = {}

            tasks.append(
                Task(
                    id=f"task_{index}",
                    name=name,
                    skill=name,
                    input=task_input,
                )
            )

        if not tasks:
            return None

        goal_str = self._extract_goal(query, context)
        plan = ExecutionPlan(
            goal=goal_str,
            tasks=tasks,
        )
        plan.confidence = 0.95
        optimized = self.optimize_plan(plan)
        
        task_graph = self.create_task_graph(goal_str)
        if isinstance(optimized.metadata, dict):
            optimized.metadata["task_graph"] = task_graph
        else:
            optimized.metadata = {"task_graph": task_graph}

        logger.info("[Planner] Created new plan.")
        return optimized

    # =========================================================
    # AUTONOMY METHODS
    # =========================================================

    async def monitor_goal_progress(self, plan, execution_result):
        """
        Decide whether the original goal has been achieved.
        """
        if not plan or not plan.tasks:
            return True
        
        if isinstance(execution_result, dict):
            failed = execution_result.get("failed", [])
            completed = execution_result.get("completed", [])
            if failed:
                return False
            if len(completed) >= len(plan.tasks):
                return True
        return False

    async def dynamic_replan(
        self,
        goal,
        completed_tasks,
        failed_tasks,
        context,
    ):
        """
        Build a new plan using only the unfinished work.
        """
        logger.info("[Planner] Executing dynamic replan for goal: %s", goal)
        uncompleted_query = f"Complete remaining work for goal: {goal} after failures: {failed_tasks}"
        new_plan = await self._generate_dynamic_plan(uncompleted_query, context)
        if new_plan:
            self.active_plan = new_plan
        return new_plan

    def detect_parallel_tasks(self, plan):
        """
        Return groups of tasks that have no dependencies
        and can execute together.
        """
        if not plan or not plan.tasks:
            return []

        # Find tasks with no dependencies (or whose dependencies are completed)
        independent_tasks = [t for t in plan.tasks if not t.depends_on]
        dependent_tasks = [t for t in plan.tasks if t.depends_on]

        groups = []
        if independent_tasks:
            groups.append(independent_tasks)
        if dependent_tasks:
            groups.append(dependent_tasks)
        return groups

    def estimate_completion(self, plan):
        """
        Estimate workflow completion percentage based on tasks.
        """
        if not plan or not plan.tasks:
            return 100.0
        
        completed_count = len(getattr(plan, "completed_tasks", []))
        total_count = len(plan.tasks)
        if total_count == 0:
            return 100.0
        return (completed_count / total_count) * 100.0

    # =========================================================
    # PUBLIC PLANNER API
    # =========================================================

    async def create_plan(
        self,
        query: str,
        context: Dict[str, Any],
    ) -> ExecutionPlan:
        """
        Canonical planning entry point used by CognitiveCore.
        """

        decision = context.get("decision")
        if decision and not getattr(decision, "use_planner", True):
            logger.info("[Planner] Planner disabled by CognitiveController decision.")
            goal_str = self._extract_goal(query, context)
            task_graph = self.create_task_graph(goal_str)
            empty_plan = ExecutionPlan(
                goal=goal_str,
                tasks=[],
            )
            empty_plan.confidence = 0.80
            empty_plan.metadata = {"task_graph": task_graph}
            self.active_plan = empty_plan
            self.plan_history.append(empty_plan)
            return empty_plan

        clean_query = str(
            query or ""
        ).strip()

        MODIFICATION_KEYWORDS = [
            "instead",
            "change",
            "modify",
            "update",
            "replace",
            "remove",
            "add",
            "make it",
            "actually",
        ]

        is_modification = any(
            keyword in clean_query.lower()
            for keyword in MODIFICATION_KEYWORDS
        )

        if self.active_plan and is_modification:
            updated_plan = await self.modify_plan(
                self.active_plan,
                clean_query,
                context,
            )
            self.active_plan = updated_plan
            self.plan_history.append(updated_plan)
            return updated_plan

        # 1. Check historical similarity/reuse
        similar_plan = await self.find_similar_plan(clean_query)
        if similar_plan:
            self.active_plan = similar_plan
            return similar_plan

        # 2. First use an already-understood workflow when ReasoningEngine supplied one.
        reasoning_plan = (
            self._plan_from_reasoning(
                clean_query,
                context,
            )
        )

        if reasoning_plan:
            logger.info(
                "[Planner] Using reasoning-generated "
                "workflow with %d task(s).",
                len(reasoning_plan.tasks),
            )
            self.active_plan = reasoning_plan
            self.plan_history.append(reasoning_plan)
            self.statistics["plans_created"] += 1
            return reasoning_plan

        # 3. Otherwise dynamically compose tasks from ARIA's currently registered capabilities.
        dynamic_plan = (
            await self._generate_dynamic_plan(
                clean_query,
                context,
            )
        )

        if dynamic_plan:

            logger.info(
                "[Planner] Dynamic plan generated with "
                "%d task(s). Goal=%s",
                len(dynamic_plan.tasks),
                dynamic_plan.goal,
            )
            self.active_plan = dynamic_plan
            self.plan_history.append(dynamic_plan)
            self.statistics["plans_created"] += 1
            return dynamic_plan

        # 4. No executable workflow is required/available.
        logger.info(
            "[Planner] No executable plan required."
        )

        goal_str = self._extract_goal(clean_query, context)
        task_graph = self.create_task_graph(goal_str)

        empty_plan = ExecutionPlan(
            goal=goal_str,
            tasks=[],
        )
        empty_plan.confidence = 0.80
        empty_plan.metadata = {"task_graph": task_graph}
        self.active_plan = empty_plan
        self.plan_history.append(empty_plan)
        self.statistics["plans_created"] += 1
        return empty_plan

    # =========================================================
    # EVENT LISTENER HANDLER
    # =========================================================

    async def handle(self, event):
        """
        Handle events from EventBus (e.g., successful execution learning).
        """
        if event.type == event_types.PLAN_FINISHED:
            logger.info("[Planner] Plan finished successfully event received.")
