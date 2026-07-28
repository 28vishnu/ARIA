import json
import logging
import re
from typing import Dict, Any
from brain.plan import ExecutionPlan
from brain.task import Task

logger = logging.getLogger("aria")

GREETINGS = {
    "hi", "hello", "hey", "hii", "hi there", "hello there",
    "good morning", "good afternoon", "good evening", "greetings",
    "how are you", "what's up", "sup"
}

class Planner:
    def __init__(self, llm_router):
        self.llm_router = llm_router

    async def create_plan(self, goal: str, context: Dict[str, Any]) -> ExecutionPlan:
        """Generates a structured execution plan, handling greetings and blocking sensitive identifier queries."""
        cleaned_goal = goal.lower().strip()

        if cleaned_goal in GREETINGS or len(cleaned_goal) <= 3:
            logger.info("[Planner] Detected casual greeting. Skipping task orchestration.")
            return ExecutionPlan(goal=goal, tasks=[], confidence=1.0)

        app_state = context.get("app_state")
        skill_manager = app_state.registry.get("skill_manager") if app_state and app_state.registry.has("skill_manager") else None

        available_skills = {}
        if skill_manager:
            if isinstance(skill_manager.skills, dict):
                available_skills = {name: skill.description for name, skill in skill_manager.skills.items()}
            elif isinstance(skill_manager.skills, list):
                available_skills = {s.name: s.description for s in skill_manager.skills}

        if not available_skills:
            available_skills = {
                "document": "Document retrieval",
                "memory": "Personal memory",
                "calculator": "Calculations",
                "profile": "User profile"
            }

        agent_result = context.get("agent_result")

        if agent_result:
            available_skills["agent"] = (
                f"Specialized {agent_result.agent} agent is available for this request."
            )

            logger.info(
                "[Planner] Agent available: %s",
                agent_result.agent
            )

        if self.llm_router is None:
            return ExecutionPlan(goal=goal, tasks=[Task(id="1", name="default", skill="document", input={"query": goal}, depends_on=[])], confidence=0.5)

        skills_desc_str = "\n".join([f"- **{name}**: {desc}" for name, desc in available_skills.items()])

        prompt = f"""
You are ARIA's autonomous task planner. Break down the user's goal into discrete execution tasks using ONLY the registered skills.

CRITICAL RULES:
1. Greetings, small talk, and conversational chat must return an empty tasks list.
2. Requests for sensitive government identifiers (such as Aadhaar, RRN, MyNumber, passports, PAN numbers, or secure identity cards) are strictly restricted and must NOT be mapped to 'profile' or 'memory' skills. Return an empty tasks list for restricted ID requests so the system handles them securely.
3. If a specialized 'agent' skill is listed in the available skills, prefer using the 'agent' skill over generic 'chat' or basic execution skills for tasks matching the agent's specialization.

IMPORTANT MINIMALITY & ROUTING RULES:
- Only choose a skill if it is absolutely required.
- Never use the 'calculator' skill unless the user explicitly asks for arithmetic or mathematical computation.
- Never use 'search' unless real-time or external facts/information retrieval is required.
- If a specialized 'agent' is available for the request, prefer a single 'agent' task instead of combining unnecessary skills.
- Produce the smallest valid plan possible.

Available Skills:
{skills_desc_str}

User Goal: "{goal}"

Instructions:
1. Output STRICT JSON only.
2. Schema:
{{
    "goal": "{goal}",
    "confidence": 0.95,
    "tasks": [
        {{
            "id": "1",
            "name": "Short name",
            "skill": "skill_name_from_list",
            "input": {{"query": "instruction"}},
            "depends_on": []
        }}
    ]
}}
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

            return ExecutionPlan(
                goal=plan_data.get("goal", goal),
                tasks=tasks,
                confidence=float(plan_data.get("confidence", 0.9))
            )
        except Exception:
            logger.exception("[Planner] Failed to parse plan.")
            return ExecutionPlan(goal=goal, tasks=[], confidence=0.4)
