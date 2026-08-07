from typing import Optional


class CodingEngine:

    def __init__(self, llm_router):
        self.llm = llm_router

    async def process(
        self,
        query: str,
        context: Optional[str] = None,
    ) -> str:

        messages = [
            {
                "role": "system",
                "content": (
                    "You are ARIA's dedicated software engineering expert.\n"
                    "Produce production-quality code.\n"
                    "Explain clearly when requested.\n"
                    "Prefer best practices.\n"
                    "Never invent APIs."
                ),
            }
        ]

        if context:
            messages.append(
                {
                    "role": "system",
                    "content": context,
                }
            )

        messages.append(
            {
                "role": "user",
                "content": query,
            }
        )

        return await self.llm.chat(messages)