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
    ARIA Phase-4 autonomous planner.

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
        self.plan_history = []

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

            plan = ExecutionPlan(
                goal=goal,
                tasks=[],
                confidence=1.0,
            )
            # Convert a single plan into executable steps
            if not hasattr(plan, "steps") or not plan.steps:
                plan.steps = [
                    {
                        "id": 1,
                        "description": plan.goal if hasattr(plan, "goal") else "Execute request",
                        "status": "pending",
                    }
                ]
            self.plan_history.append(plan)
            if len(self.plan_history) > 100:
                self.plan_history.pop(0)
            return plan

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

            plan = ExecutionPlan(
                goal=goal,
                tasks=[],
                confidence=0.5,
            )
            # Convert a single plan into executable steps
            if not hasattr(plan, "steps") or not plan.steps:
                plan.steps = [
                    {
                        "id": 1,
                        "description": plan.goal if hasattr(plan, "goal") else "Execute request",
                        "status": "pending",
                    }
                ]
            self.plan_history.append(plan)
            if len(self.plan_history) > 100:
                self.plan_history.pop(0)
            return plan

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
You are ARIA's autonomous cognitive planner.

Your job is to convert the user's goal into the SMALLEST SAFE
execution plan needed to accomplish the goal.

Do not plan by matching keywords mechanically.

Instead reason about:

1. What the user ultimately wants.
2. What information is already available in context.
3. What information must be retrieved.
4. Which registered capability can obtain that information.
5. Which real-world actions must happen.
6. Which tasks depend on outputs from previous tasks.
7. Whether one task is sufficient or multiple tasks are required.

=============================================================
AVAILABLE INFORMATION CAPABILITIES
============================================================={skills_desc}

=============================================================
AVAILABLE ACTION CAPABILITIES
============================================================={actions_desc}

=============================================================
CURRENT CONTEXT
=============================================================

Active document:{context.get("document", {})}

Relevant memory available:{bool(context.get("memory"))}

Conversation context:{context.get("conversation", {})}

Capability availability:{context.get("capabilities", {})}

=============================================================
ACTIVE AUTONOMOUS GOAL
=============================================================

{context.get("autonomous_goal") or context.get("goal") or "No active autonomous goal."}

When an autonomous goal is present:

1. Treat the active goal as the larger objective.
2. Prioritize its current next_subgoal when planning.
3. Do not mark the entire goal complete unless the current workflow
   actually accomplishes the relevant goal/subgoal.
4. Preserve dependencies between tasks.
5. If the current request advances the active goal, create the smallest
   executable workflow that advances it.
6. If there is no active autonomous goal, plan normally from the user's goal.

=============================================================
USER GOAL
============================================================={goal}

=============================================================
CORE PLANNING PRINCIPLES
=============================================================

1. Understand the user's GOAL, not merely individual words.

2. Use ONLY registered skills and actions listed above.

3. Never invent capabilities.

4. Produce the smallest plan that fully accomplishes the goal.

5. A simple conversational request that requires no tool,
   skill, document, memory, or action should return no tasks.

6. A request may require MULTIPLE capabilities.

Example conceptual workflow:

    retrieve information
        ↓
    reason about information
        ↓
    transform result
        ↓
    perform action

7. Tasks may depend on earlier tasks.

Use:

    "depends_on": ["1"]

when a task requires task 1 to finish first.

8. Pass previous task output using references:

    {{{{TASK_ID.FIELD}}}}

Example:

    {{{{1.content}}}}

9. Never assume a previous task's output.

Explicitly connect dependent tasks using both:

    depends_on

and the required output reference.

10. Dependencies must reference EXISTING EARLIER task IDs.

11. Never create circular dependencies.

12. Do not create unnecessary tasks.

13. Do not use notification actions merely to display a normal
    answer to the user.

14. Never bypass permissions or confirmations.

The execution layer handles permissions.

15. Never place passwords, API keys, authentication tokens,
    credentials, or other secrets into generated action parameters.

=============================================================
CONTEXTUAL REASONING
=============================================================

ARIA may already possess useful context.

For example:

- an active uploaded document
- retrieved personal memory
- previous conversation context
- outputs from earlier tasks

Use this context when appropriate.

Do NOT automatically use the active document for every question.

Do NOT automatically use memory merely because memory exists.

Choose the source that is semantically relevant to the user's goal.

If multiple information sources are required, create separate tasks
and combine their outputs through a later reasoning/skill task.

=============================================================
MULTI-STEP REQUESTS
=============================================================

A single user message may contain several connected goals.

Example:

    "Find the latest information, summarize it,
     save the summary to notes.txt, then notify me."

This should become a dependency chain such as:

    web retrieval
        ↓
    synthesis
        ↓
    file write
        ↓
    notification

Do NOT collapse multiple dependent operations into one task.

Do NOT require hard-coded command combinations.

Infer the workflow from the meaning of the request.

=============================================================
FILE ACTION
=============================================================

If file_action is registered:

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

When file content comes from an earlier task:

{{
    "task_type": "action",
    "action_name": "file_action",
    "params": {{
        "mode": "write",
        "path": "example.txt",
        "content": "{{{{2.content}}}}"
    }},
    "depends_on": ["2"]
}}

=============================================================
WEB INFORMATION
=============================================================

If a registered web-search capability exists, use it when the
request genuinely requires current/external web information.

If raw search results need interpretation, summarization,
comparison, or explanation, add a reasoning/research skill after
retrieval.

Example:

Task 1:
    retrieve current information

Task 2:
    synthesize Task 1

Task 2 depends on Task 1.

Use the actual output field provided by the registered capability.

For web_search_action the result field is:

    {{{{1.results}}}}

Do not assume:

    {{{{1.content}}}}

for web search results.

=============================================================
DOCUMENT INFORMATION
=============================================================

When the user's goal requires information contained in an uploaded
or active document, use a registered document capability if one is
available.

The document task should answer/retrieve only the information needed
for the larger goal.

Example conceptual request:

    "Get my Monday classes from the document and save them."

Possible plan:

    document reasoning
        ↓
    file write

The file task must consume the document task's output.

Do not hard-code concepts such as Monday, timetable, classes,
subjects, PDFs, or filenames into routing logic.

The planner should infer their meaning from the user's goal.

=============================================================
MEMORY
=============================================================

Use memory capabilities when the goal requires persistent personal
knowledge previously stored by ARIA.

Do not confuse:

    information in an uploaded document

with:

    persistent personal memory

If both are needed, they may be separate tasks.

=============================================================
NOTIFICATION ACTION
=============================================================

If notification_action is registered:

{{
    "task_type": "action",
    "action_name": "notification_action",
    "params": {{
        "message": "message here"
    }}
}}

A notification may consume previous output:

{{
    "task_type": "action",
    "action_name": "notification_action",
    "params": {{
        "message": "{{{{2.content}}}}"
    }},
    "depends_on": ["2"]
}}

=============================================================
OUTPUT CONTRACT
=============================================================

Return STRICT JSON ONLY.

No markdown.
No explanation.
No text before or after the JSON.

Schema:

{{
    "goal": "{goal}",
    "confidence": 0.95,
    "tasks": [
        {{
            "id": "1",
            "name": "Short descriptive task name",
            "task_type": "skill",
            "skill": "registered_skill_name",
            "action_name": null,
            "input": {{}},
            "params": {{}},
            "depends_on": [],
            "requires_confirmation": false,
            "max_retries": 2,
            "priority": 1
        }}
    ]
}}

For SKILL tasks:

    task_type = "skill"
    skill = exact registered skill name
    action_name = null
    params = {{}}

For ACTION tasks:

    task_type = "action"
    skill = ""
    action_name = exact registered action name
    input = {{}}

=============================================================
FINAL CHECK BEFORE RESPONDING
=============================================================

Before producing JSON, verify:

- Does the plan accomplish the COMPLETE user goal?
- Are all capabilities registered?
- Is every task actually necessary?
- Are dependencies correct?
- Does every output reference point to an earlier task?
- Are actions ordered after the information they require?
- Did you avoid inventing capabilities?
- Did you avoid unnecessary notifications?
- Did you preserve permission boundaries?
- Are confirmation requirements correctly specified?
- Are retry counts within safe limits?
- Are task priorities valid integers?
- Are all task IDs unique?
- Does every dependency reference an earlier task?
- Does the final ExecutionPlan pass validate_dependencies()?

Then return the JSON only.
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
                task="planning",
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
                ).strip()

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

                depends_on = raw_task.get("depends_on", [])

                if not isinstance(depends_on, list):
                    logger.warning(
                        "[Planner] Invalid depends_on for task %s",
                        task_id,
                    )
                    continue

                depends_on = [
                    str(dep).strip()
                    for dep in depends_on
                    if str(dep).strip()
                ]

                # Dependencies must reference existing earlier tasks.
                invalid_dependencies = [
                    dep
                    for dep in depends_on
                    if dep not in known_ids
                ]

                if invalid_dependencies:
                    logger.warning(
                        "[Planner] Invalid dependencies for task %s: %s",
                        task_id,
                        invalid_dependencies,
                    )
                    continue

                # Prevent self-dependency explicitly.
                if task_id in depends_on:
                    logger.warning(
                        "[Planner] Self-dependency rejected for task %s",
                        task_id,
                    )
                    continue

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
                    depends_on=depends_on,
                    requires_confirmation=bool(
                        raw_task.get(
                            "requires_confirmation",
                            False,
                        )
                    ),
                    max_retries=max(
                        0,
                        int(
                            raw_task.get(
                                "max_retries",
                                2,
                            )
                        )
                    ),
                    priority=int(
                        raw_task.get(
                            "priority",
                            1,
                        )
                    ),
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

            plan = ExecutionPlan(
                goal=str(
                    plan_data.get(
                        "goal",
                        goal,
                    )
                ),
                tasks=tasks,
                confidence=confidence,
                metadata={
                    "phase": 4,
                    "valid": True,
                    "supports_actions": True,
                    "supports_dependencies": True,
                    "supports_result_references": True,

                    # ---------------------------------------------------------
                    # PHASE 4 — AUTONOMOUS GOAL OWNERSHIP
                    # ---------------------------------------------------------
                    # Identifies which autonomous goal owns this workflow.
                    # CognitiveCore uses this to prevent unrelated workflows
                    # from advancing the active goal.
                    "autonomous_goal_id": str(
                        (
                            context.get("autonomous_goal")
                            or context.get("goal")
                            or {}
                        ).get("goal_id", "")
                        if isinstance(
                            context.get("autonomous_goal")
                            or context.get("goal")
                            or {},
                            dict,
                        )
                        else ""
                    ),

                    "autonomous_goal_title": str(
                        (
                            context.get("autonomous_goal")
                            or context.get("goal")
                            or {}
                        ).get("title", "")
                        if isinstance(
                            context.get("autonomous_goal")
                            or context.get("goal")
                            or {},
                            dict,
                        )
                        else ""
                    ),
                },
            )

            # ---------------------------------------------
            # FINAL PLAN VALIDATION
            # ---------------------------------------------

            if not plan.validate_dependencies():
                logger.error(
                    "[Planner] Invalid execution plan rejected."
                )

                plan = ExecutionPlan(
                    goal=goal,
                    tasks=[],
                    confidence=0.0,
                    metadata={
                        "phase": 4,
                        "valid": False,
                        "reason": "invalid_dependencies",
                    },
                )

                self.plan_history.append(plan)

                if len(self.plan_history) > 100:
                    self.plan_history.pop(0)

                return plan

            # Convert a single plan into executable steps
            if not hasattr(plan, "steps") or not plan.steps:
                plan.steps = [
                    {
                        "id": 1,
                        "description": plan.goal if hasattr(plan, "goal") else "Execute request",
                        "status": "pending",
                    }
                ]
            self.plan_history.append(plan)
            if len(self.plan_history) > 100:
                self.plan_history.pop(0)
            return plan

        except Exception:

            logger.exception(
                "[Planner] Failed to create execution plan."
            )

            plan = ExecutionPlan(
                goal=goal,
                tasks=[],
                confidence=0.4,
            )
            # Convert a single plan into executable steps
            if not hasattr(plan, "steps") or not plan.steps:
                plan.steps = [
                    {
                        "id": 1,
                        "description": plan.goal if hasattr(plan, "goal") else "Execute request",
                        "status": "pending",
                    }
                ]
            self.plan_history.append(plan)
            if len(self.plan_history) > 100:
                self.plan_history.pop(0)
            return plan

    def next_step(self, plan):

        for step in plan.steps:
            if step["status"] == "pending":
                return step

        return None

    def last_plan(self):
        if not self.plan_history:
            return None
        return self.plan_history[-1]

    def clear_history(self):
        self.plan_history.clear()
