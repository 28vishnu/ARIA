import json
import logging
from typing import Dict, Any

from skills.base import BaseSkill, SkillResponse


logger = logging.getLogger("aria")


class ResearchSkill(BaseSkill):
    """
    Synthesizes retrieved information into a grounded answer.

    Important:
    This skill does NOT browse the web itself.

    Retrieval:
        web_search_action

    Reasoning / synthesis:
        ResearchSkill
    """

    name = "research"

    description = (
        "Analyzes and synthesizes supplied research material, "
        "including live web-search results, into a clear and "
        "grounded answer."
    )

    version = "1.0.0"
    priority = 80
    requires_llm = True

    async def can_run(
        self,
        query: str,
        context: Dict[str, Any],
    ) -> float:

        q = str(query or "").lower()

        keywords = (
            "research",
            "search",
            "search the web",
            "latest",
            "news",
            "find out",
            "look up",
            "summarize",
            "summary",
            "analyse",
            "analyze",
            "compare",
            "findings",
            "sources",
            "web",
        )

        if any(keyword in q for keyword in keywords):
            return 0.95

        # ResearchSkill can still synthesize supplied material
        # even when the wording does not explicitly say research.
        task_input = context.get("task_input", {})

        if isinstance(task_input, dict) and task_input:
            return 0.70

        return 0.10

    async def execute(
        self,
        query: str,
        context: Dict[str, Any],
    ) -> SkillResponse:

        try:
            app_state = context.get("app_state")

            if app_state is None:
                return SkillResponse(
                    success=False,
                    confidence=0.0,
                    source=self.name,
                    data=None,
                    error="Application state unavailable.",
                )

            registry = getattr(
                app_state,
                "registry",
                None,
            )

            if registry is None:
                return SkillResponse(
                    success=False,
                    confidence=0.0,
                    source=self.name,
                    data=None,
                    error="Service registry unavailable.",
                )

            llm_router = registry.get(
                "llm_router"
            )

            if llm_router is None:
                return SkillResponse(
                    success=False,
                    confidence=0.0,
                    source=self.name,
                    data=None,
                    error="LLM router unavailable.",
                )

            # -------------------------------------------------
            # INPUT FROM PREVIOUS WORKFLOW TASK
            # -------------------------------------------------

            task_input = context.get(
                "task_input",
                {},
            )

            if not isinstance(task_input, dict):
                task_input = {
                    "content": task_input
                }

            research_material = (
                task_input.get("research_material")
                or task_input.get("results")
                or task_input.get("content")
                or task_input.get("data")
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
                    default=str,
                )

            else:

                research_text = str(
                    research_material or ""
                ).strip()

            if not research_text:

                return SkillResponse(
                    success=False,
                    confidence=0.0,
                    source=self.name,
                    data=None,
                    error="No research material was supplied.",
                )

            # Prevent accidentally sending an enormous retrieval
            # payload to the model.
            max_chars = 50_000

            if len(research_text) > max_chars:
                research_text = (
                    research_text[:max_chars]
                    + "\n\n[Research material truncated]"
                )

            # -------------------------------------------------
            # SYNTHESIS
            # -------------------------------------------------

            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are ARIA's research synthesis engine.\n\n"
                        "Your job is to answer the user's request "
                        "using the supplied research material.\n\n"

                        "Rules:\n"
                        "- Base factual claims on the supplied material.\n"
                        "- Do not claim you searched sources yourself.\n"
                        "- Do not invent facts missing from the material.\n"
                        "- Prioritize recent and relevant information.\n"
                        "- Combine duplicate findings.\n"
                        "- Explain conflicting information when present.\n"
                        "- Preserve useful source titles and URLs.\n"
                        "- Produce a natural answer for the user.\n"
                        "- Never expose internal workflow task IDs.\n"
                        "- Never mention internal tools or execution details.\n"
                        "- Do not merely say that execution completed.\n"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "USER REQUEST:\n"
                        f"{query}\n\n"
                        "RESEARCH MATERIAL:\n"
                        f"{research_text}"
                    ),
                },
            ]

            answer = await llm_router.chat(
                messages,
                temperature=0.2,
                max_tokens=1800,
            )

            answer = str(
                answer or ""
            ).strip()

            if not answer:

                return SkillResponse(
                    success=False,
                    confidence=0.0,
                    source=self.name,
                    data=None,
                    error="Research synthesis returned an empty answer.",
                )

            logger.info(
                "[ResearchSkill] Research synthesis completed."
            )

            # Keep "content" as the canonical composable output.
            #
            # This allows later tasks to reference:
            #
            # {{2.content}}
            #
            return SkillResponse(
                success=True,
                confidence=0.95,
                source=self.name,
                data={
                    "content": answer,
                    "response": answer,
                },
                error=None,
            )

        except Exception as exc:

            logger.exception(
                "[ResearchSkill] Research synthesis failed."
            )

            return SkillResponse(
                success=False,
                confidence=0.0,
                source=self.name,
                data=None,
                error=str(exc),
            )