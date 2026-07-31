import json
from typing import Dict, Any

from skills.base import BaseSkill, SkillResponse


class ResearchSkill(BaseSkill):
    """
    Synthesizes supplied research material into a grounded,
    useful answer.

    This skill does NOT browse the web itself.
    Web retrieval is handled by web_search_action.
    """

    name = "research"

    description = (
        "Analyzes and synthesizes research material, including web "
        "search results, into a clear grounded answer."
    )

    async def can_handle(
        self,
        query: str,
        context: Dict[str, Any],
    ) -> float:

        q = str(query or "").lower()

        keywords = (
            "research",
            "search",
            "latest",
            "news",
            "summarize",
            "summary",
            "analyse",
            "analyze",
            "findings",
            "sources",
            "web",
        )

        if any(word in q for word in keywords):
            return 0.90

        return 0.20

    async def execute(
        self,
        query: str,
        context: Dict[str, Any],
    ) -> SkillResponse:

        app_state = context.get("app_state")

        if app_state is None:
            return SkillResponse(
                success=False,
                data={},
                error="Application state unavailable.",
            )

        llm_router = app_state.registry.get(
            "llm_router"
        )

        # The Executor may provide structured task input
        # through the execution context.
        task_input = context.get(
            "task_input",
            {}
        )

        if not isinstance(task_input, dict):
            task_input = {}

        research_material = (
            task_input.get("research_material")
            or task_input.get("results")
            or task_input.get("content")
            or task_input
        )

        if isinstance(
            research_material,
            (dict, list),
        ):
            research_text = json.dumps(
                research_material,
                ensure_ascii=False,
                indent=2,
            )
        else:
            research_text = str(
                research_material or ""
            )

        messages = [
            {
                "role": "system",
                "content": (
                    "You are ARIA's research synthesis engine. "
                    "Answer the user's request using the supplied "
                    "research material. Do not pretend to have "
                    "searched sources that are not supplied. "
                    "Prioritize recent and relevant information. "
                    "Clearly summarize the important findings. "
                    "When source titles or URLs are present, preserve "
                    "them when useful. Do not mention internal task "
                    "IDs, workflows, tools, or execution details."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"USER REQUEST:\n{query}\n\n"
                    f"RESEARCH MATERIAL:\n{research_text}"
                ),
            },
        ]

        try:
            answer = await llm_router.chat(
                messages,
                temperature=0.2,
                max_tokens=1800,
            )

            answer = str(answer or "").strip()

            if not answer:
                return SkillResponse(
                    success=False,
                    data={},
                    error="Research synthesis returned no answer.",
                )

            return SkillResponse(
                success=True,
                data={
                    "content": answer,
                    "response": answer,
                },
            )

        except Exception as exc:

            return SkillResponse(
                success=False,
                data={},
                error=str(exc),
            )