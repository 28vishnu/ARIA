from typing import Any, Dict, List

from brain.agents.base_agent import BaseAgent, AgentResponse


class GeneralAgent(BaseAgent):
    """
    General conversational assistant for requests that do not need a
    specialist. It is deliberately thin: CognitiveCore owns memory, tools,
    routing, and final response formatting.

    When no language model is configured the agent fails truthfully instead of
    returning an empty success.
    """

    name = "chat"
    aliases = ("general", "assistant", "conversation")

    description = "General conversational assistant."
    version = "1.0.0"
    priority = 50
    timeout_seconds = 45.0
    max_retries = 1

    async def can_handle(
        self,
        query: str,
        context: Dict[str, Any],
    ) -> float:
        text = str(query or "").strip()
        if not text:
            return 0.0
        # Low confidence by design: specialist agents must win when relevant.
        return 0.35

    async def execute(
        self,
        query: str,
        context: Dict[str, Any],
    ) -> AgentResponse:

        history = context.get("conversation_history")
        history_text = self._format_history(history)

        prompt = query
        if history_text:
            prompt = (
                f"Recent conversation:\n{history_text}\n\n"
                f"Current user message:\n{query}"
            )

        answer = await self.complete_with_llm(
            context,
            (
                "You are JARVIS, a direct and helpful personal assistant. "
                "Answer the user's message using the supplied conversation "
                "context. Never claim you searched the web, ran code, or "
                "completed an action unless that result is present in the "
                "context. If you do not know something, say so."
            ),
            prompt,
        )

        if not answer:
            return AgentResponse(
                success=False,
                confidence=0.0,
                agent=self.name,
                data={},
                error=(
                    "The general assistant is unavailable because no "
                    "language model is configured or the model returned no "
                    "answer."
                ),
            )

        return AgentResponse(
            success=True,
            confidence=0.6,
            agent=self.name,
            data={"response": answer},
        )

    @staticmethod
    def _format_history(history: Any) -> str:
        if not isinstance(history, list):
            return ""
        lines: List[str] = []
        for turn in history[-6:]:
            if not isinstance(turn, dict):
                continue
            user_message = str(turn.get("user") or "").strip()
            assistant_message = str(turn.get("assistant") or "").strip()
            if user_message:
                lines.append(f"User: {user_message[:600]}")
            if assistant_message:
                lines.append(f"Assistant: {assistant_message[:600]}")
        return "\n".join(lines)
