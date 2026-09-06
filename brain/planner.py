import json
import logging
import re
from typing import Dict, Any, Optional, List, Set

from brain.plan import ExecutionPlan
from brain.task import Task

logger = logging.getLogger("aria")


GREETINGS = {
    "hi",
    "hello",
    "hey",
    "hii",
    "hi there",
    "hello there",
    "good morning",
    "good afternoon",
    "good evening",
    "greetings",
    "how are you",
    "what's up",
    "sup",
}


class Planner:
    """
    ARIA's canonical execution planner.

    Responsibilities:
      - Convert a user/autonomous goal into the smallest executable workflow.
      - Use only capabilities actually registered in the current app state.
      - Preserve task dependencies and result references.
      - Respect action permission/confirmation metadata.
      - Support dynamic replanning after execution failures.

    The planner does not execute tasks itself.
    """

    PLANNER_VERSION = "11.4"
    MAX_HISTORY = 100
    DEFAULT_MAX_RETRIES = 2
    MAX_ALLOWED_RETRIES = 5
    DEFAULT_PRIORITY = 1

    def __init__(self, llm_router=None):
        self.llm_router = llm_router
        self.plan_history: List[ExecutionPlan] = []

    # ---------------------------------------------------------
    # Generic helpers
    # ---------------------------------------------------------

    @staticmethod
    def _clean_goal(goal: Any) -> str:
        return str(goal or "").strip()

    @staticmethod
    def _safe_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _safe_float(value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _safe_dict(value: Any) -> Dict[str, Any]:
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _safe_list(value: Any) -> List[Any]:
        return value if isinstance(value, list) else []

    def _remember_plan(self, plan: ExecutionPlan) -> ExecutionPlan:
        self.plan_history.append(plan)

        if len(self.plan_history) > self.MAX_HISTORY:
            del self.plan_history[:-self.MAX_HISTORY]

        return plan

    @staticmethod
    def _ensure_steps(plan: ExecutionPlan) -> ExecutionPlan:
        """
        Preserve the compatibility `steps` representation expected by
        older execution paths while keeping `tasks` as the canonical plan.
        """
        steps = getattr(plan, "steps", None)

        if not isinstance(steps, list) or not steps:
            goal = getattr(plan, "goal", "Execute request")
            plan.steps = [
                {
                    "id": 1,
                    "description": str(goal or "Execute request"),
                    "status": "pending",
                }
            ]

        return plan

    @staticmethod
    def _extract_registry(app_state):
        registry = getattr(app_state, "registry", None)
        if registry is None:
            return None
        return registry

    @staticmethod
    def _registry_has(registry, name: str) -> bool:
        if registry is None:
            return False

        try:
            return bool(registry.has(name))
        except Exception:
            try:
                return registry.get(name) is not None
            except Exception:
                return False

    @staticmethod
    def _registry_get(registry, name: str):
        if registry is None:
            return None

        try:
            return registry.get(name)
        except Exception:
            return None

    # ---------------------------------------------------------
    # Capability discovery
    # ---------------------------------------------------------

    def _discover_capabilities(self, context: Dict[str, Any]):
        """
        Discover capabilities without inventing unavailable actions.

        Phase 11 adds ToolManager as a central capability source while
        preserving the existing SkillManager/ActionManager contracts.
        """

        context = self._safe_dict(context)
        app_state = context.get("app_state")
        registry = self._extract_registry(app_state)

        skill_manager = None
        action_manager = None
        tool_manager = None

        if registry is not None:
            if self._registry_has(registry, "skill_manager"):
                skill_manager = self._registry_get(
                    registry,
                    "skill_manager",
                )

            if self._registry_has(registry, "action_manager"):
                action_manager = self._registry_get(
                    registry,
                    "action_manager",
                )

            if self._registry_has(registry, "tool_manager"):
                tool_manager = self._registry_get(
                    registry,
                    "tool_manager",
                )

        # Existing registered skills remain authoritative.
        available_skills: Dict[str, str] = {}

        skills = getattr(skill_manager, "skills", {}) if skill_manager else {}

        if isinstance(skills, dict):
            for name, skill in skills.items():
                if not name:
                    continue

                available_skills[str(name)] = str(
                    getattr(skill, "description", "") or ""
                )

        elif isinstance(skills, list):
            for skill in skills:
                name = getattr(skill, "name", None)
                if not name:
                    continue

                available_skills[str(name)] = str(
                    getattr(skill, "description", "") or ""
                )

        # Existing actions remain authoritative.
        available_actions: Dict[str, Dict[str, Any]] = {}

        actions = getattr(action_manager, "actions", {}) if action_manager else {}

        if isinstance(actions, dict):
            for name, action in actions.items():
                if not name:
                    continue

                available_actions[str(name)] = {
                    "description": str(
                        getattr(action, "description", "") or ""
                    ),
                    "permission_level": str(
                        getattr(
                            action,
                            "permission_level",
                            "confirm",
                        )
                        or "confirm"
                    ),
                }

        # ToolManager is a routing/execution layer. It is not blindly
        # converted into planner tasks because not every BaseTool is
        # necessarily exposed as an executable task target.
        available_tools: Dict[str, str] = {}

        if tool_manager is not None:
            tools = getattr(tool_manager, "tools", {})

            if isinstance(tools, dict):
                for name, tool in tools.items():
                    if not name:
                        continue

                    description = getattr(
                        tool,
                        "description",
                        "",
                    ) or getattr(
                        tool,
                        "__doc__",
                        "",
                    ) or ""

                    available_tools[str(name)] = str(
                        description
                    ).strip()

        # Phase-4 compatibility fallbacks. These are conceptual skills only
        # and are retained because the original Planner supported them.
        if not available_skills:
            available_skills = {
                "document": "Document retrieval",
                "memory": "Personal memory",
                "calculator": "Calculations",
                "profile": "User profile",
            }

        agent_result = context.get("agent_result")

        if agent_result:
            agent_name = getattr(agent_result, "agent", None)

            if agent_name:
                available_skills["agent"] = (
                    f"Specialized {agent_name} agent is available "
                    "for this request."
                )

        return {
            "skill_manager": skill_manager,
            "action_manager": action_manager,
            "tool_manager": tool_manager,
            "skills": available_skills,
            "actions": available_actions,
            "tools": available_tools,
        }

    # ---------------------------------------------------------
    # Planner prompt
    # ---------------------------------------------------------

    def _build_prompt(
        self,
        goal: str,
        context: Dict[str, Any],
        capabilities: Dict[str, Any],
    ) -> str:
        skills = self._safe_dict(capabilities.get("skills"))
        actions = self._safe_dict(capabilities.get("actions"))
        tools = self._safe_dict(capabilities.get("tools"))

        skills_desc = "\n".join(
            f"- {name}: {description}"
            for name, description in skills.items()
        ) or "- No registered skills available"

        actions_desc = "\n".join(
            (
                f"- {name}: {info.get('description', '')} "
                f"(permission={info.get('permission_level', 'confirm')})"
            )
            for name, info in actions.items()
        ) or "- No executable actions available"

        tools_desc = "\n".join(
            f"- {name}: {description}"
            for name, description in tools.items()
        ) or "- No centrally registered tools available"

        active_goal = (
            context.get("autonomous_goal")
            or context.get("goal")
            or "No active autonomous goal."
        )

        return f"""
You are ARIA's autonomous cognitive planner, version {self.PLANNER_VERSION}.

Convert the user's goal into the SMALLEST SAFE execution plan needed
to accomplish it.

Do not execute anything. Do not invent capabilities.

AVAILABLE REGISTERED SKILLS
{skills_desc}

AVAILABLE REGISTERED ACTIONS
{actions_desc}

CENTRALLY REGISTERED TOOLS
{tools_desc}

CURRENT CONTEXT
Active document: {context.get("document", {{}})}
Relevant memory available: {bool(context.get("memory"))}
Conversation context: {context.get("conversation", {{}})}
Capabilities: {context.get("capabilities", {{}})}
Previous plan: {context.get("last_plan", context.get("previous_plan", {{}}))}
Replanning: {bool(context.get("replanning", False))}
Failure reason: {context.get("failure_reason", "")}
Failed task: {context.get("failed_task", {{}})}

ACTIVE AUTONOMOUS GOAL
{active_goal}

USER GOAL
{goal}

PLANNING RULES

1. Understand the complete goal, not isolated keywords.
2. Use ONLY registered skills/actions/capabilities listed above.
3. Produce the smallest plan that fully accomplishes the goal.
4. A simple conversational request that requires no capability should
   return no tasks.
5. Multiple dependent operations must remain separate tasks.
6. Every dependency must reference an earlier task ID.
7. Never create circular or self-dependencies.
8. Result references must use the form {{{{TASK_ID.FIELD}}}} and point
   to an earlier task.
9. Never assume output fields that a capability does not provide.
10. Never bypass permissions or confirmations.
11. Never place passwords, API keys, authentication tokens, credentials,
    or other secrets into generated parameters.
12. Keep retries bounded between 0 and {self.MAX_ALLOWED_RETRIES}.
13. Priorities must be integers.
14. Do not create a notification task merely to display a normal answer.
15. When an active autonomous goal exists, advance only the relevant
    goal/subgoal rather than marking an unrelated workflow complete.
16. If replanning, use the failure information and previous workflow
    context to avoid blindly repeating the same failed approach.

ACTION TASK:
{{
  "task_type": "action",
  "action_name": "exact_registered_action",
  "skill": "",
  "input": {{}},
  "params": {{}},
  "depends_on": [],
  "requires_confirmation": false,
  "max_retries": 2,
  "priority": 1
}}

SKILL TASK:
{{
  "task_type": "skill",
  "skill": "exact_registered_skill",
  "action_name": null,
  "input": {{}},
  "params": {{}},
  "depends_on": [],
  "requires_confirmation": false,
  "max_retries": 2,
  "priority": 1
}}

For web_search_action, if it is registered, its result field is
{{{{TASK_ID.results}}}}, not {{content}}.

Return STRICT JSON ONLY:

{{
  "goal": "{goal}",
  "confidence": 0.95,
  "tasks": []
}}

Before returning JSON verify:
- all task targets are registered
- IDs are unique
- dependencies point only to earlier tasks
- retry counts are safe
- priorities are integers
- result references point to earlier tasks
- no secrets are present
- the plan is dependency-valid
"""

    # ---------------------------------------------------------
    # JSON parsing
    # ---------------------------------------------------------

    @staticmethod
    def _clean_json_response(raw_response: Any) -> str:
        cleaned = str(raw_response or "").strip()

        if cleaned.startswith("```"):
            cleaned = re.sub(
                r"^```(?:json)?\s*",
                "",
                cleaned,
                flags=re.IGNORECASE,
            )
            cleaned = re.sub(
                r"\s*```$",
                "",
                cleaned,
            ).strip()

        return cleaned

    @staticmethod
    def _parse_json_object(raw_response: Any) -> Dict[str, Any]:
        cleaned = Planner._clean_json_response(raw_response)

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(
                r"\{.*\}",
                cleaned,
                flags=re.DOTALL,
            )

            if not match:
                raise

            data = json.loads(match.group(0))

        if not isinstance(data, dict):
            raise ValueError("Planner response must be a JSON object.")

        return data

    # ---------------------------------------------------------
    # Task validation
    # ---------------------------------------------------------

    @staticmethod
    def _validate_result_references(
        task_data: Dict[str, Any],
        known_ids: Set[str],
    ) -> bool:
        """
        Validate {{task_id.field}} references found anywhere in input/params.

        References to future/nonexistent task IDs are rejected before the
        task enters the ExecutionPlan.
        """

        serialized = json.dumps(
            {
                "input": task_data.get("input", {}),
                "params": task_data.get("params", {}),
            },
            ensure_ascii=False,
        )

        references = re.findall(
            r"\{\{\s*([A-Za-z0-9_-]+)\.([A-Za-z0-9_.-]+)\s*\}\}",
            serialized,
        )

        for task_id, _field in references:
            if task_id not in known_ids:
                return False

        return True

    def _task_from_raw(
        self,
        raw_task: Dict[str, Any],
        capabilities: Dict[str, Any],
        known_ids: Set[str],
        fallback_id: int,
    ) -> Optional[Task]:
        if not isinstance(raw_task, dict):
            return None

        task_id = str(
            raw_task.get("id", fallback_id)
        ).strip()

        if not task_id or task_id in known_ids:
            logger.warning(
                "[Planner] Duplicate/invalid task id rejected: %s",
                task_id,
            )
            return None

        task_type = str(
            raw_task.get("task_type", "skill")
            or "skill"
        ).lower().strip()

        skills = self._safe_dict(capabilities.get("skills"))
        actions = self._safe_dict(capabilities.get("actions"))

        skill = str(
            raw_task.get("skill", "") or ""
        ).strip()

        action_name = raw_task.get("action_name")

        if action_name is not None:
            action_name = str(action_name).strip() or None

        if task_type == "action":
            if not action_name or action_name not in actions:
                logger.warning(
                    "[Planner] Rejected unknown action: %s",
                    action_name,
                )
                return None

            skill = ""

        elif task_type == "skill":
            if not skill or skill not in skills:
                logger.warning(
                    "[Planner] Rejected unknown skill: %s",
                    skill,
                )
                return None

            action_name = None

        else:
            logger.warning(
                "[Planner] Invalid task type: %s",
                task_type,
            )
            return None

        depends_on = raw_task.get("depends_on", [])

        if not isinstance(depends_on, list):
            logger.warning(
                "[Planner] Invalid depends_on for task %s",
                task_id,
            )
            return None

        depends_on = [
            str(dep).strip()
            for dep in depends_on
            if str(dep).strip()
        ]

        if len(set(depends_on)) != len(depends_on):
            logger.warning(
                "[Planner] Duplicate dependency rejected for task %s",
                task_id,
            )
            return None

        # Only earlier task IDs may be referenced.
        invalid_dependencies = [
            dep for dep in depends_on if dep not in known_ids
        ]

        if invalid_dependencies:
            logger.warning(
                "[Planner] Invalid dependencies for task %s: %s",
                task_id,
                invalid_dependencies,
            )
            return None

        if task_id in depends_on:
            logger.warning(
                "[Planner] Self-dependency rejected for task %s",
                task_id,
            )
            return None

        if not self._validate_result_references(
            raw_task,
            known_ids,
        ):
            logger.warning(
                "[Planner] Invalid/future result reference in task %s",
                task_id,
            )
            return None

        input_data = raw_task.get("input", {})
        params = raw_task.get("params", {})

        if not isinstance(input_data, dict):
            input_data = {}

        if not isinstance(params, dict):
            params = {}

        retries = self._safe_int(
            raw_task.get(
                "max_retries",
                self.DEFAULT_MAX_RETRIES,
            ),
            self.DEFAULT_MAX_RETRIES,
        )

        retries = max(
            0,
            min(retries, self.MAX_ALLOWED_RETRIES),
        )

        priority = self._safe_int(
            raw_task.get(
                "priority",
                self.DEFAULT_PRIORITY,
            ),
            self.DEFAULT_PRIORITY,
        )

        priority = max(0, priority)

        confirmation = raw_task.get(
            "requires_confirmation",
            False,
        )

        if isinstance(confirmation, str):
            confirmation = confirmation.strip().lower() in {
                "true",
                "yes",
                "1",
                "on",
            }
        else:
            confirmation = bool(confirmation)

        # Action permission metadata is authoritative when available.
        # The planner may request confirmation, but it must not downgrade
        # an action that is explicitly marked for confirmation.
        if task_type == "action":
            permission_level = str(
                actions.get(action_name, {}).get(
                    "permission_level",
                    "confirm",
                )
                or "confirm"
            ).lower()

            if permission_level in {
                "confirm",
                "confirmation",
                "approval",
                "high",
                "dangerous",
            }:
                confirmation = True

        name = str(
            raw_task.get(
                "name",
                f"Task {task_id}",
            )
            or f"Task {task_id}"
        ).strip()

        return Task(
            id=task_id,
            name=name,
            skill=skill,
            task_type=task_type,
            action_name=action_name,
            input=input_data,
            params=params,
            depends_on=depends_on,
            requires_confirmation=confirmation,
            max_retries=retries,
            priority=priority,
        )

    # ---------------------------------------------------------
    # Plan construction
    # ---------------------------------------------------------

    def _empty_plan(
        self,
        goal: str,
        confidence: float,
        *,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExecutionPlan:
        plan = ExecutionPlan(
            goal=goal,
            tasks=[],
            confidence=max(
                0.0,
                min(
                    self._safe_float(confidence, 0.0),
                    1.0,
                ),
            ),
            metadata=metadata or {},
        )
        return self._ensure_steps(plan)

    def _autonomous_goal_metadata(
        self,
        context: Dict[str, Any],
    ) -> Dict[str, str]:
        active_goal = (
            context.get("autonomous_goal")
            or context.get("goal")
            or {}
        )

        if not isinstance(active_goal, dict):
            return {
                "autonomous_goal_id": "",
                "autonomous_goal_title": "",
            }

        return {
            "autonomous_goal_id": str(
                active_goal.get("goal_id", "") or ""
            ).strip(),
            "autonomous_goal_title": str(
                active_goal.get("title", "") or ""
            ).strip(),
        }

    def _construct_plan(
        self,
        goal: str,
        context: Dict[str, Any],
        capabilities: Dict[str, Any],
        plan_data: Dict[str, Any],
    ) -> ExecutionPlan:
        raw_tasks = plan_data.get("tasks", [])

        if not isinstance(raw_tasks, list):
            raise ValueError("Planner tasks must be a list.")

        tasks: List[Task] = []
        known_ids: Set[str] = set()

        for index, raw_task in enumerate(raw_tasks, start=1):
            task = self._task_from_raw(
                raw_task,
                capabilities,
                known_ids,
                index,
            )

            if task is None:
                continue

            tasks.append(task)
            known_ids.add(task.id)

        confidence = self._safe_float(
            plan_data.get("confidence", 0.9),
            0.9,
        )

        metadata = {
            "phase": 4,
            "phase11": True,
            "planner_version": self.PLANNER_VERSION,
            "valid": True,
            "supports_actions": True,
            "supports_dependencies": True,
            "supports_result_references": True,
            "replanning": bool(context.get("replanning", False)),
            "failure_reason": str(
                context.get("failure_reason", "") or ""
            ),
            **self._autonomous_goal_metadata(context),
        }

        plan = ExecutionPlan(
            goal=str(
                plan_data.get("goal", goal) or goal
            ),
            tasks=tasks,
            confidence=max(
                0.0,
                min(confidence, 1.0),
            ),
            metadata=metadata,
        )

        if not plan.validate_dependencies():
            raise ValueError(
                "Generated execution plan failed dependency validation."
            )

        return self._ensure_steps(plan)

    # ---------------------------------------------------------
    # Public planning
    # ---------------------------------------------------------

    async def create_plan(
        self,
        goal: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> ExecutionPlan:
        context = self._safe_dict(context)
        cleaned_goal = self._clean_goal(goal)

        # Casual conversation is deliberately not orchestrated.
        if (
            cleaned_goal.lower() in GREETINGS
            or len(cleaned_goal) <= 3
        ):
            logger.info(
                "[Planner] Casual conversation detected. "
                "Skipping orchestration."
            )

            plan = self._empty_plan(
                cleaned_goal,
                1.0,
                metadata={
                    "phase": 4,
                    "phase11": True,
                    "planner_version": self.PLANNER_VERSION,
                    "valid": True,
                    "reason": "casual_conversation",
                },
            )

            return self._remember_plan(plan)

        capabilities = self._discover_capabilities(context)

        # No LLM: return a safe empty plan rather than fabricating tasks.
        if self.llm_router is None:
            logger.warning(
                "[Planner] LLM router unavailable; returning safe empty plan."
            )

            plan = self._empty_plan(
                cleaned_goal,
                0.5,
                metadata={
                    "phase": 4,
                    "phase11": True,
                    "planner_version": self.PLANNER_VERSION,
                    "valid": True,
                    "reason": "llm_unavailable",
                    **self._autonomous_goal_metadata(context),
                },
            )

            return self._remember_plan(plan)

        prompt = self._build_prompt(
            cleaned_goal,
            context,
            capabilities,
        )

        messages = [
            {
                "role": "system",
                "content": (
                    "You are ARIA's deterministic execution planner. "
                    "Return valid JSON only."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ]

        try:
            raw_response = await self.llm_router.chat(
                messages,
                temperature=0.0,
                max_tokens=1400,
                task="planning",
            )

            plan_data = self._parse_json_object(raw_response)

            plan = self._construct_plan(
                cleaned_goal,
                context,
                capabilities,
                plan_data,
            )

            logger.info(
                "[Planner] Created plan with %d task(s): %s",
                len(getattr(plan, "tasks", []) or []),
                [
                    (
                        task.id,
                        task.task_type,
                        task.action_name or task.skill,
                        task.depends_on,
                    )
                    for task in (
                        getattr(plan, "tasks", []) or []
                    )
                ],
            )

            return self._remember_plan(plan)

        except Exception:
            logger.exception(
                "[Planner] Failed to create execution plan."
            )

            plan = self._empty_plan(
                cleaned_goal,
                0.4,
                metadata={
                    "phase": 4,
                    "phase11": True,
                    "planner_version": self.PLANNER_VERSION,
                    "valid": False,
                    "reason": "planner_error",
                    **self._autonomous_goal_metadata(context),
                },
            )

            return self._remember_plan(plan)

    # ---------------------------------------------------------
    # Dynamic replanning
    # ---------------------------------------------------------

    async def dynamic_replan(
        self,
        goal: str,
        context: Optional[Dict[str, Any]] = None,
        failed_task=None,
        failure_reason: str = "",
        previous_plan=None,
    ) -> ExecutionPlan:
        """
        Replan after a workflow failure.

        The new planning context preserves the active autonomous goal,
        failed task details, previous workflow state, and failure reason.
        """

        replan_context = dict(context or {})

        replan_context["replanning"] = True
        replan_context["failure_reason"] = str(
            failure_reason or ""
        )

        if failed_task is not None:
            replan_context["failed_task"] = {
                "id": str(
                    getattr(failed_task, "id", "") or ""
                ).strip(),
                "name": str(
                    getattr(failed_task, "name", "") or ""
                ).strip(),
                "action_name": str(
                    getattr(failed_task, "action_name", "") or ""
                ).strip(),
                "skill": str(
                    getattr(failed_task, "skill", "") or ""
                ).strip(),
                "error": str(
                    getattr(failed_task, "error", "") or ""
                ).strip(),
            }

        if previous_plan is not None:
            replan_context["previous_plan"] = {
                "goal": str(
                    getattr(previous_plan, "goal", "") or ""
                ),
                "completed_tasks": list(
                    getattr(
                        previous_plan,
                        "completed_tasks",
                        [],
                    )
                    or []
                ),
                "failed_tasks": list(
                    getattr(
                        previous_plan,
                        "failed_tasks",
                        [],
                    )
                    or []
                ),
                "skipped_tasks": list(
                    getattr(
                        previous_plan,
                        "skipped_tasks",
                        [],
                    )
                    or []
                ),
            }

        logger.info(
            "[Planner] Dynamic replan requested | goal=%s | "
            "failed_task=%s | reason=%s",
            goal,
            getattr(failed_task, "id", None),
            failure_reason,
        )

        return await self.create_plan(
            goal=goal,
            context=replan_context,
        )

    # ---------------------------------------------------------
    # Compatibility helpers
    # ---------------------------------------------------------

    def next_step(self, plan):
        steps = getattr(plan, "steps", []) or []

        for step in steps:
            if isinstance(step, dict) and step.get("status") == "pending":
                return step

        return None

    def last_plan(self):
        if not self.plan_history:
            return None

        return self.plan_history[-1]

    def clear_history(self):
        self.plan_history.clear()
