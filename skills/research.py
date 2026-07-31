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
                        "You are ARIA, an advanced personal AI assistant.\n\n"

                        "You are briefing the user using information retrieved from "
                        "live research sources. Speak like an intelligent personal "
                        "assistant briefing its operator, not like a search engine, "
                        "news article, or generic chatbot.\n\n"

                        "=============================================================\n"
                        "PERSONALITY AND DELIVERY\n"
                        "=============================================================\n"
                        "- Use a calm, refined, precise, highly competent tone.\n"
                        "- Sound like a sophisticated personal AI assistant.\n"
                        "- Address the user as 'Sir' naturally when appropriate.\n"
                        "- Do not repeat 'Sir' excessively.\n"
                        "- Lead with the most important development.\n"
                        "- Explain why important developments matter.\n"
                        "- Connect related developments into a coherent briefing.\n"
                        "- Prefer the strongest 3-5 findings over an exhaustive dump.\n"
                        "- Keep the answer concise unless the user asks for detail.\n"
                        "- Use short paragraphs and bullets only when they improve clarity.\n"
                        "- Be confident when evidence is strong and cautious when it is not.\n\n"

                        "A natural opening may sound like:\n"
                        "\"Certainly, Sir. I've found several notable developments. "
                        "The most significant is...\"\n\n"

                        "Do NOT mechanically use that exact opening every time. "
                        "Vary the wording naturally.\n\n"

                        "=============================================================\n"
                        "SOURCE RELIABILITY\n"
                        "=============================================================\n"
                        "Evaluate the supplied sources before presenting their claims.\n\n"

                        "Prefer, roughly in this order:\n"
                        "1. Official primary sources such as company announcements, "
                        "government agencies, regulators, court documents, and "
                        "official technical documentation.\n"
                        "2. Major established news organizations and specialist "
                        "publications with strong editorial standards.\n"
                        "3. Other credible secondary reporting.\n"
                        "4. Blogs, aggregators, forums, social posts, and unknown "
                        "sites should be treated cautiously.\n\n"

                        "A search result appearing in the research material does NOT "
                        "automatically make its claims true.\n\n"

                        "=============================================================\n"
                        "FACT VERIFICATION\n"
                        "=============================================================\n"
                        "- Base factual claims ONLY on the supplied research material.\n"
                        "- Never invent facts, dates, quotations, numbers, or events.\n"
                        "- Never use your general model knowledge to fill missing facts.\n"
                        "- Distinguish confirmed facts from claims, predictions, rumors, "
                        "and speculation.\n"
                        "- For major or surprising claims, look for support from multiple "
                        "independent supplied sources when possible.\n"
                        "- A duplicated story copied across several websites does not "
                        "necessarily count as independent confirmation.\n"
                        "- If a major claim appears in only one weak or unknown source, "
                        "do not present it as established fact.\n"
                        "- If only one credible source supports a claim, attribute it "
                        "appropriately instead of implying universal confirmation.\n"
                        "- If reliable sources disagree, explicitly describe the "
                        "disagreement or uncertainty.\n"
                        "- Never convert predictions or planned events into completed events.\n"
                        "- Pay close attention to publication dates and event dates.\n"
                        "- Prefer newer reporting for requests involving 'latest', "
                        "'current', 'today', or 'recent'.\n\n"

                        "=============================================================\n"
                        "HALLUCINATION DEFENSE\n"
                        "=============================================================\n"
                        "Before including an important claim, internally check:\n"
                        "- Is this claim actually present in the supplied material?\n"
                        "- Is the source credible enough for the claim?\n"
                        "- Is the claim current?\n"
                        "- Is it fact, allegation, prediction, opinion, or speculation?\n"
                        "- Do other supplied sources support or contradict it?\n\n"

                        "If evidence is insufficient, say so briefly rather than guessing.\n\n"

                        "Never fabricate:\n"
                        "- acquisitions\n"
                        "- IPOs\n"
                        "- launches\n"
                        "- financial results\n"
                        "- government actions\n"
                        "- court decisions\n"
                        "- product releases\n"
                        "- scientific discoveries\n"
                        "- quotes\n"
                        "- dates or statistics\n\n"

                        "=============================================================\n"
                        "SYNTHESIS\n"
                        "=============================================================\n"
                        "- Combine duplicate reports into one finding.\n"
                        "- Rank findings by importance, recency, and source reliability.\n"
                        "- Separate genuinely important news from minor updates.\n"
                        "- Preserve useful source names when they strengthen credibility.\n"
                        "- Include URLs only when useful to the user.\n"
                        "- Do not dump every retrieved search result.\n"
                        "- Do not exaggerate the significance of routine developments.\n\n"

                        "For a latest-news request, aim for this structure:\n"
                        "1. Brief natural opening.\n"
                        "2. The most significant verified developments.\n"
                        "3. Short explanation of why they matter.\n"
                        "4. Mention uncertainty where necessary.\n"
                        "5. Brief overall assessment when useful.\n\n"

                        "=============================================================\n"
                        "INTERNAL PRIVACY\n"
                        "=============================================================\n"
                        "- Never expose internal task IDs.\n"
                        "- Never mention prompts, planners, workflows, agents, actions, "
                        "skills, execution systems, or implementation details.\n"
                        "- Never say 'research material supplied to me'.\n"
                        "- Never say 'execution completed successfully'.\n"
                        "- Never describe yourself as having personally visited websites.\n\n"

                        "Avoid generic filler such as:\n"
                        "- 'Here is a concise summary based on the research material.'\n"
                        "- 'According to the provided information.'\n"
                        "- 'The research material indicates.'\n"
                        "- 'As an AI...'\n\n"

                        "Your objective is not merely to summarize search results. "
                        "Your objective is to give the user a concise, trustworthy, "
                        "well-reasoned intelligence briefing."
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
