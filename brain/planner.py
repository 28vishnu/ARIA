import json
import logging
import re
from typing import Dict, Any

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
    ARIA Phase-3 planner.

    Produces plans containing either:

    - skill tasks
    - action tasks

    Action tasks may depend on earlier tasks and may reference
    previous task outputs using:

        {{task_id.field}}

    Example:

        {{2.content}}
    """

    def __init__(self, llm_router):
        self.llm_router = llm_router

    async def create_plan(
        self,
        goal: str,
        context: Dict[str, Any],
    ) -> ExecutionPlan:

        cleaned_goal = str(goal or "").lower().strip()

        # -----------------------------------------------------
        # FAST CONVERSATIONAL EXIT
        # -----------------------------------------------------

        if cleaned_goal in GREETINGS or len(cleaned_goal) <= 3:
            logger.info(
                "[Planner] Casual conversation detected. "
                "Skipping orchestration."
            )

            return ExecutionPlan(
                goal=goal,
                tasks=[],
                confidence=1.0,
            )

        # -----------------------------------------------------
        # DISCOVER REGISTERED SKILLS + ACTIONS
        # -----------------------------------------------------

        app_state = context.get("app_state")

        skill_manager = None
        action_manager = None

        if app_state:

            if app_state.registry.has("skill_manager"):
                skill_manager = app_state.registry.get(
                    "skill_manager"
                )

            if app_state.registry.has("action_manager"):
                action_manager = app_state.registry.get(
                    "action_manager"
                )

        available_skills = {}

        if skill_manager:

            skills = getattr(
                skill_manager,
                "skills",
                {}
            )

            if isinstance(skills, dict):
                available_skills = {
                    name: getattr(
                        skill,
                        "description",
                        ""
                    )
                    for name, skill in skills.items()
                }

            elif isinstance(skills, list):
                available_skills = {
                    skill.name: getattr(
                        skill,
                        "description",
                        ""
                    )
                    for skill in skills
                }

        available_actions = {}

        if action_manager:

            actions = getattr(
                action_manager,
                "actions",
                {}
            )

            if isinstance(actions, dict):

                available_actions = {
                    name: {
                        "description": getattr(
                            action,
                            "description",
                            ""
                        ),
                        "permission_level": getattr(
                            action,
                            "permission_level",
                            "confirm"
                        ),
                    }
                    for name, action in actions.items()
                }

        # -----------------------------------------------------
        # SAFE FALLBACK SKILLS
        # -----------------------------------------------------

        if not available_skills:

            available_skills = {
                "document": "Document retrieval",
                "memory": "Personal memory",
                "calculator": "Calculations",
                "profile": "User profile",
            }

        # -----------------------------------------------------
        # AGENT AVAILABILITY
        # -----------------------------------------------------

        agent_result = context.get("agent_result")

        if agent_result:

            available_skills["agent"] = (
                f"Specialized {agent_result.agent} agent "
                "is available for this request."
            )

        # -----------------------------------------------------
        # NO LLM
        # -----------------------------------------------------

        if self.llm_router is None:

            return ExecutionPlan(
                goal=goal,
                tasks=[],
                confidence=0.5,
            )

        # -----------------------------------------------------
        # DESCRIPTIONS
        # -----------------------------------------------------

        skills_desc = "\n".join(
            f"- {name}: {description}"
            for name, description
            in available_skills.items()
        )

        actions_desc = "\n".join(
            (
                f"- {name}: "
                f"{info['description']} "
                f"(permission={info['permission_level']})"
            )
            for name, info
            in available_actions.items()
        )

        if not actions_desc:
            actions_desc = "- No executable actions available"

        # -----------------------------------------------------
        # PLANNER PROMPT
        # -----------------------------------------------------

        prompt = f"""
You are ARIA's autonomous execution planner.

Convert the user's goal into the SMALLEST SAFE ordered execution
plan necessary to accomplish it.

ARIA has two execution mechanisms:

1. SKILLS
Skills produce information or reasoning.

2. ACTIONS
Actions cause real operations such as writing files or sending
notifications.

AVAILABLE SKILLS:

{skills_desc}

AVAILABLE ACTIONS:

{actions_desc}

USER GOAL:

{goal}

=============================================================
CRITICAL RULES
=============================================================

1. Use ONLY skills and actions listed above.

2. Never invent an action or skill.

3. Greetings, casual conversation and normal questions that do
   not require orchestration should return an empty tasks list.

4. Use the smallest valid plan.

5. Use an ACTION when the user requests a real operation.

6. Use a SKILL when information/reasoning is required.

7. Tasks may depend on previous tasks using "depends_on".

8. If one task needs output from another task, reference it with:

   {{{{TASK_ID.FIELD}}}}

Example:

Task 1 reads a file and returns:

{{
    "content": "deployment passed"
}}

A later action may use:

{{
    "message": "{{{{1.content}}}}"
}}

9. Dependencies MUST reference existing earlier task IDs.

10. Never create circular dependencies.

11. Never bypass permission requirements. Permission handling
    happens later in the execution system.

12. Do not place secrets, credentials, tokens, passwords or
    sensitive identifiers into action parameters.

13. Requests involving secure government identifiers must not
    be converted into profile/memory retrieval plans.

=============================================================
FILE ACTION
=============================================================

If file_action is available:

WRITE:

{{
    "task_type": "action",
    "action_name": "file_action",
    "params": {{
        "mode": "write",
        "path": "example.txt",
        "content": "hello"
    }}
}}

READ:

{{
    "task_type": "action",
    "action_name": "file_action",
    "params": {{
        "mode": "read",
        "path": "example.txt"
    }}
}}

=============================================================
NOTIFICATION ACTION
=============================================================

If notification_action is available:

{{
    "task_type": "action",
    "action_name": "notification_action",
    "params": {{
        "message": "message here"
    }}
}}

Or use previous output:

{{
    "message": "{{{{2.content}}}}"
}}

=============================================================
OUTPUT
=============================================================

Return STRICT JSON only.

Schema:

{{
    "goal": "{goal}",
    "confidence": 0.95,
    "tasks": [
        {{
            "id": "1",
            "name": "Short descriptive name",

            "task_type": "skill OR action",

            "skill": "",
            "action_name": null,

            "input": {{}},
            "params": {{}},

            "depends_on": []
        }}
    ]
}}

For skill tasks:

task_type = "skill"
skill = registered skill name
action_name = null
params = {{}}

For action tasks:

task_type = "action"
skill = ""
action_name = registered action name
input = {{}}
"""

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
                max_tokens=1200,
            )

            cleaned = str(raw_response).strip()

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

            plan_data = json.loads(cleaned)

            raw_tasks = plan_data.get(
                "tasks",
                []
            )

            if not isinstance(raw_tasks, list):
                raise ValueError(
                    "Planner tasks must be a list."
                )

            tasks = []

            known_ids = set()

            for raw_task in raw_tasks:

                if not isinstance(raw_task, dict):
                    continue

                task_id = str(
                    raw_task.get(
                        "id",
                        len(tasks) + 1,
                    )
                )

                if task_id in known_ids:
                    logger.warning(
                        "[Planner] Duplicate task id rejected: %s",
                        task_id,
                    )
                    continue

                task_type = str(
                    raw_task.get(
                        "task_type",
                        "skill",
                    )
                ).lower().strip()

                skill = str(
                    raw_task.get(
                        "skill",
                        "",
                    )
                    or ""
                ).strip()

                action_name = raw_task.get(
                    "action_name"
                )

                if action_name is not None:
                    action_name = str(
                        action_name
                    ).strip()

                # ---------------------------------------------
                # VALIDATE TARGET
                # ---------------------------------------------

                if task_type == "action":

                    if (
                        not action_name
                        or action_name
                        not in available_actions
                    ):

                        logger.warning(
                            "[Planner] Rejected unknown action: %s",
                            action_name,
                        )

                        continue

                    skill = ""

                elif task_type == "skill":

                    if (
                        not skill
                        or skill
                        not in available_skills
                    ):

                        logger.warning(
                            "[Planner] Rejected unknown skill: %s",
                            skill,
                        )

                        continue

                    action_name = None

                else:

                    logger.warning(
                        "[Planner] Invalid task type: %s",
                        task_type,
                    )

                    continue

                # ---------------------------------------------
                # VALIDATE DEPENDENCIES
                # ---------------------------------------------

                depends_on = raw_task.get(
                    "depends_on",
                    [],
                )

                if not isinstance(
                    depends_on,
                    list,
                ):
                    depends_on = []

                depends_on = [
                    str(dep)
                    for dep in depends_on
                ]

                # Dependencies must point backwards.
                valid_dependencies = [
                    dep
                    for dep in depends_on
                    if dep in known_ids
                ]

                task = Task(
                    id=task_id,
                    name=str(
                        raw_task.get(
                            "name",
                            f"Task {task_id}",
                        )
                    ),
                    skill=skill,
                    task_type=task_type,
                    action_name=action_name,
                    input=(
                        raw_task.get(
                            "input",
                            {},
                        )
                        if isinstance(
                            raw_task.get(
                                "input",
                                {},
                            ),
                            dict,
                        )
                        else {}
                    ),
                    params=(
                        raw_task.get(
                            "params",
                            {},
                        )
                        if isinstance(
                            raw_task.get(
                                "params",
                                {},
                            ),
                            dict,
                        )
                        else {}
                    ),
                    depends_on=valid_dependencies,
                )

                tasks.append(task)
                known_ids.add(task_id)

            confidence = float(
                plan_data.get(
                    "confidence",
                    0.9,
                )
            )

            confidence = max(
                0.0,
                min(confidence, 1.0),
            )

            logger.info(
                "[Planner] Created plan with %d task(s): %s",
                len(tasks),
                [
                    (
                        task.id,
                        task.task_type,
                        task.action_name or task.skill,
                        task.depends_on,
                    )
                    for task in tasks
                ],
            )

            return ExecutionPlan(
                goal=str(
                    plan_data.get(
                        "goal",
                        goal,
                    )
                ),
                tasks=tasks,
                confidence=confidence,
                metadata={
                    "phase": 3,
                    "supports_actions": True,
                    "supports_dependencies": True,
                    "supports_result_references": True,
                },
            )

        except Exception:

            logger.exception(
                "[Planner] Failed to create execution plan."
            )

            return ExecutionPlan(
                goal=goal,
                tasks=[],
                confidence=0.4,
            )