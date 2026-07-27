import json
import logging
import re
from typing import Dict, Any
from brain.plan import ExecutionPlan
from brain.task import Task

logger = logging.getLogger("aria")

class Planner:
    def __init__(self, llm_router):
        self.llm_router = llm_router

    async def create_plan(self, goal: str, context: Dict[str, Any]) -> ExecutionPlan:
        """Generates a structured multi-step execution plan exclusively utilizing registered skills."""
        app_state = context.get("app_state")
        skill_manager = app_state.registry.get("skill_manager") if app_state and app_state.registry.has("skill_manager") else None
        
        available_skills = {s.name: s.description for s in skill_manager.skills} if skill_manager else {
            "document": "Document retrieval",
            "memory": "Personal memory",
            "calculator": "Calculations",
            "profile": "User profile"
        }

        if self.llm_router is None:
            return ExecutionPlan(
                goal=goal,
                tasks=[Task(id="1", name="default_skill_execution", skill="document", input={"query": goal}, depends_on=[])],
                confidence=0.5
            )

        skills_desc_str = "\n".join([f"- **{name}**: {desc}" for name, desc in available_skills.items()])
        
        prompt = f"""
You are ARIA's autonomous task planner. Your job is to break down the user's goal into discrete execution tasks using ONLY the registered skills provided below.

Available Skills:
{skills_desc_str}

User Goal: "{goal}"

Instructions:
1. Output STRICT JSON only. No markdown formatting blocks if possible, or standard JSON.
2. The schema must match:
{{
    "goal": "{goal}",
    "confidence": 0.95,
    "tasks": [
        {{
            "id": "1",
            "name": "Short descriptive name",
            "skill": "skill_name_from_list",
            "input": {{"query": "specific instruction for this task"}},
            "depends_on": []
        }}
    ]
}}
3. If a task depends on the output of a previous task, list the parent task id in `depends_on`.
"""
        messages = [
            {"role": "system", "content": "You are a deterministic task planner. Return JSON only."},
            {"role": "user", "content": prompt}
        ]

        try:
            raw_response = await self.llm_router.chat(messages, temperature=0.0, max_tokens=600)
            cleaned = re.sub(r'```(?:json)?\s*', '', raw_response)
            cleaned = re.sub(r'\s*```', '', cleaned).strip()
            
            plan_data = json.loads(cleaned)
            tasks = []
            for t in plan_data.get("tasks", []):
                tasks.append(Task(
                    id=str(t.get("id")),
                    name=str(t.get("name")),
                    skill=str(t.get("skill")),
                    input=t.get("input", {}),
                    depends_on=t.get("depends_on", [])
                ))
            
            plan = ExecutionPlan(
                goal=plan_data.get("goal", goal),
                tasks=tasks,
                confidence=float(plan_data.get("confidence", 0.9))
            )
            logger.info("[Planner] Goal: '%s' | Tasks: %d | Estimated Confidence: %.2f", plan.goal, len(plan.tasks), plan.confidence)
            return plan

        except Exception:
            logger.exception("[Planner] Failed to parse structured execution plan, falling back to direct match.")
            return ExecutionPlan(
                goal=goal,
                tasks=[Task(id="1", name="fallback_execution", skill="document", input={"query": goal}, depends_on=[])],
                confidence=0.4
            )
