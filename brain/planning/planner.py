import json
import logging
import re
from typing import Dict, Any, List, Optional

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
    ):
        self.memory_router = memory_router
        self.llm_router = llm_router
        self.skill_manager = skill_manager
        self.action_manager = action_manager

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
    # CONTEXT EXTRACTION
    # =========================================================

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
    # TASK NORMALIZATION
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
            or ""
        ).strip()

        action = str(
            raw_task.get("action")
            or ""
        ).strip()

        capability = (
            skill
            or action
        )

        if not capability:
            return None

        task_id = str(
            raw_task.get("id")
            or f"task_{index}"
        )

        task_name = str(
            raw_task.get("name")
            or capability
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

        # Preserve whether this is a skill or action.
        if action and not skill:
            task_input.setdefault(
                "action_name",
                action,
            )

        return Task(
            id=task_id,
            name=task_name,
            skill=capability,
            input=task_input,
        )

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

        conversation = context.get(
            "conversation",
            {},
        ) or {}

        document = context.get(
            "document",
            {},
        ) or {}

        memory = context.get(
            "memory",
            [],
        ) or []

        planner_prompt = f"""
You are ARIA's workflow planner.

Your job is to convert the user's goal into the smallest safe
sequence of executable tasks using ONLY the capabilities listed
below.

USER REQUEST:
{query}

GOAL:
{goal}

AVAILABLE CAPABILITIES:
{json.dumps(capabilities, default=str)}

ACTIVE DOCUMENT CONTEXT:
{json.dumps(document, default=str)}

CONVERSATION CONTEXT:
{json.dumps(conversation, default=str)}

RELEVANT MEMORY EXISTS:
{bool(memory)}

RULES:

1. Never invent a skill or action.
2. Use only names present in AVAILABLE CAPABILITIES.
3. Prefer the smallest plan that fully completes the goal.
4. A simple request should normally use one task.
5. A compound request may use multiple ordered tasks.
6. Later tasks may depend on results from earlier tasks.
7. Do not execute anything yourself.
8. Do not answer the user.
9. Do not create unnecessary formatting tasks.
10. Destructive or permission-sensitive actions may still be
    selected; Executor/CognitiveCore handles confirmation.
11. Preserve the user's actual goal instead of matching keywords.
12. If no available capability can perform the request, return
    an empty tasks list.

Return ONLY valid JSON in exactly this structure:

{{
  "goal": "clear description of the user's goal",
  "tasks": [
    {{
      "id": "task_1",
      "name": "short task description",
      "skill": "registered capability name",
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

            return ExecutionPlan(
                goal=plan_goal,
                tasks=tasks,
            )

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

        return ExecutionPlan(
            goal=self._extract_goal(
                query,
                context,
            ),
            tasks=tasks,
        )

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

        clean_query = str(
            query or ""
        ).strip()

        # First use an already-understood workflow when
        # ReasoningEngine supplied one.
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

            return reasoning_plan

        # Otherwise dynamically compose tasks from ARIA's
        # currently registered capabilities.
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

            return dynamic_plan

        # No executable workflow is required/available.
        logger.info(
            "[Planner] No executable plan required."
        )

        return ExecutionPlan(
            goal=self._extract_goal(
                clean_query,
                context,
            ),
            tasks=[],
        )
