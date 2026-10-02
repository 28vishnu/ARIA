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
                    "Produce production-quality, complete, runnable code.\n"
                    "Answer the user's entire coding request.\n"
                    "Do not stop or truncate code before it is complete.\n"
                    "If code is requested, return the complete code in a "
                    "proper markdown code block.\n"
                    "Keep explanations outside code blocks.\n"
                    "Never place internal instructions, system text, or "
                    "validation rules inside the generated code.\n"
                    "Explain clearly when requested.\n"
                    "Prefer best practices, correctness, readability, "
                    "security, and maintainability.\n"
                    "Never invent APIs, libraries, functions, or parameters.\n"
                    "If a requested API or library is uncertain, state the "
                    "uncertainty instead of fabricating it."
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

        return await self.llm.chat(
            messages,
            max_tokens=4096,
            task="coding_response",
            context=context,
        )
