from dataclasses import dataclass, field
from typing import Dict, Any, Optional
import logging
import re
import json

logger = logging.getLogger("aria")


@dataclass
class Intent:
    name: str
    confidence: float
    requires_planning: bool = False
    requires_tools: bool = False
    requires_documents: bool = False
    requires_memory: bool = True
    data: Dict[str, Any] = field(default_factory=dict)


class IntentAnalyzer:
    """
    ARIA's advanced semantic intent classification layer.

    Classifies user requests semantically into categories such as:
    - Chat
    - Follow-up
    - Memory
    - Planning
    - Research
    - Coding
    - Tool
    - Document
    - Web Search
    - Multi-step task
    - Clarification needed

    Returns structured metadata including execution flags.
    """

    def __init__(self, llm_router=None):
        self.llm_router = llm_router

    async def analyze(self, query: str) -> Intent:
        q = self._normalize(query)

        if not q:
            return Intent(
                name="Chat",
                confidence=0.50,
                requires_planning=False,
                requires_tools=False,
                requires_documents=False,
                requires_memory=True,
            )

        # Local rule evaluation before calling LLM
        if "compare" in q:
            return Intent("Research", 0.96, False, False, False, True)

        if q.startswith("who"):
            return Intent("Research", 0.95, False, False, False, True)

        if q.startswith("where"):
            return Intent("Research", 0.95, False, False, False, True)

        if q == "continue":
            return Intent("Follow-up", 0.99, False, False, False, True)

        if "remember" in q:
            return Intent("Memory", 0.99, False, False, False, True)

        if "plan" in q:
            return Intent("Planning", 0.95, True, False, False, True)

        # Delegate to semantic analysis if LLM router is available
        if self.llm_router and hasattr(self.llm_router, "chat"):
            semantic_intent = await self._semantic_intent(query)
            if semantic_intent is not None:
                return semantic_intent

        # Fallback local heuristics
        if q in {"hi", "hello", "hey", "good morning", "good afternoon", "good evening"}:
            return Intent("Chat", 0.99, False, False, False, True)

        if q in {"continue", "go on", "tell me more", "explain more", "next", "and", "then"}:
            return Intent("Follow-up", 0.90, False, False, False, True)

        return Intent(
            name="Chat",
            confidence=0.80,
            requires_planning=False,
            requires_tools=False,
            requires_documents=False,
            requires_memory=True,
        )

    async def _semantic_intent(self, query: str) -> Optional[Intent]:
        if not self.llm_router:
            return None

        system_prompt = """
You are ARIA's advanced semantic intent classifier.

Classify the user query into one of these exact intent categories:
- Chat
- Follow-up
- Memory
- Planning
- Research
- Coding
- Tool
- Document
- Web Search
- Multi-step task
- Clarification needed

Determine the following boolean execution requirements based on the request context:
- requires_planning (bool)
- requires_tools (bool)
- requires_documents (bool)
- requires_memory (bool)
- confidence (float between 0.0 and 1.0)

Return ONLY valid JSON in this exact structure:
{
  "intent": "CategoryName",
  "confidence": 0.95,
  "requires_planning": false,
  "requires_tools": false,
  "requires_documents": false,
  "requires_memory": true,
  "action_name": null,
  "action_params": {}
}
"""

        try:
            response = await self.llm_router.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": query},
                ],
                temperature=0.0,
                max_tokens=200,
            )

            cleaned = str(response).strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
                cleaned = re.sub(r"\s*```$", "", cleaned).strip()

            data = json.loads(cleaned)
            name = str(data.get("intent", "Chat")).strip()
            confidence = float(data.get("confidence", 0.80))
            requires_planning = bool(data.get("requires_planning", False))
            requires_tools = bool(data.get("requires_tools", False))
            requires_documents = bool(data.get("requires_documents", False))
            requires_memory = bool(data.get("requires_memory", True))

            return Intent(
                name=name,
                confidence=max(0.0, min(confidence, 1.0)),
                requires_planning=requires_planning,
                requires_tools=requires_tools,
                requires_documents=requires_documents,
                requires_memory=requires_memory,
                data={
                    "action_name": data.get("action_name"),
                    "action_params": data.get("action_params", {}),
                },
            )
        except Exception:
            logger.exception("[IntentAnalyzer] Semantic intent classification failed.")
            return None

    def _normalize(self, query: str) -> str:
        return re.sub(r"\s+", " ", str(query or "").lower()).strip()