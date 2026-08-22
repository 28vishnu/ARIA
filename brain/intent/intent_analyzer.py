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
    requires_memory: bool = False
    requires_web: bool = False
    requires_reasoning: bool = False

    data: Dict[str, Any] = field(default_factory=dict)

    @property
    def intent_type(self) -> str:
        """
        Canonical compatibility alias.

        ReasoningEngine historically uses intent_type,
        while IntentAnalyzer uses name.
        """
        return self.name

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
        self.intent_history = []  

    async def analyze(self, query: str) -> Intent:  
        q = self._normalize(query)  

        if not q:  
            intent = Intent(  
                name="Chat",  
                confidence=0.50,  
                requires_planning=False,  
                requires_tools=False,  
                requires_documents=False,  
                requires_memory=False,  
                requires_web=False,
                requires_reasoning=False,
            )  
            self.intent_history.append(intent)  
            if len(self.intent_history) > 100:  
                self.intent_history.pop(0)  
            return intent  

        # ---------------------------------------------------------
        # EXPLICIT COMPARISON REQUEST
        # ---------------------------------------------------------
        if (
            q.startswith("compare ")
            or " compare " in f" {q} "
            or q.startswith("difference between ")
        ):
            intent = Intent(
                name="Research",
                confidence=0.96,
                requires_planning=False,
                requires_tools=False,
                requires_documents=False,
                requires_memory=False,
                requires_web=False,
                requires_reasoning=True,
                data={
                    "comparison": True,
                    "action_name": None,
                    "action_params": {},
                },
            )

            self.intent_history.append(intent)

            if len(self.intent_history) > 100:
                self.intent_history.pop(0)

            return intent

        # ---------------------------------------------------------
        # FOLLOW-UP / CONTEXT-DEPENDENT REQUEST
        # ---------------------------------------------------------

        follow_up_patterns = (
            "why is it important",
            "why is this important",
            "why is that important",
            "why does it matter",
            "why is it useful",
            "how does it work",
            "how does this work",
            "how does that work",
            "how is it done",
            "how does it happen",
            "what about it",
            "what about that",
            "tell me more",
            "explain more",
            "go on",
            "continue",
            "and then",
            "what happens next",
            "why",
            "how",
        )

        is_follow_up = (
            q in {
                "continue",
                "go on",
                "tell me more",
                "explain more",
                "next",
                "and then",
                "then",
                "what about it",
                "what about that",
                "why",
                "how",
                "why is that",
                "how so",
            }
            or q.startswith(follow_up_patterns)
        )

        if is_follow_up:
            intent = Intent(
                name="Follow-up",
                confidence=0.98,
                requires_planning=False,
                requires_tools=False,
                requires_documents=False,
                requires_memory=True,
                requires_web=False,
                requires_reasoning=True,
                data={
                    "context_dependent": True,
                    "action_name": None,
                    "action_params": {},
                },
            )

            self.intent_history.append(intent)

            if len(self.intent_history) > 100:
                self.intent_history.pop(0)

            return intent

        if "remember" in q:  
            intent = Intent("Memory", 0.99, False, False, False, True, False, False)  
            self.intent_history.append(intent)  
            if len(self.intent_history) > 100:  
                self.intent_history.pop(0)  
            return intent  

        if "plan" in q:  
            intent = Intent("Planning", 0.95, True, False, False, False, False, True)  
            self.intent_history.append(intent)  
            if len(self.intent_history) > 100:  
                self.intent_history.pop(0)  
            return intent  

        # ---------------------------------------------------------
        # GENERAL KNOWLEDGE / EXPLANATION FAST PATH
        # ---------------------------------------------------------
        #
        # Ordinary questions such as:
        #   "What is photosynthesis?"
        #   "Explain gravity"
        #   "Why is the sky blue?"
        #   "How does TCP work?"
        #
        # must NEVER accidentally become weather/tool/action requests.
        #
        # Explicit web/tool requests are intentionally excluded.
        # ---------------------------------------------------------

        explicit_web = (
            "search the web" in q
            or "search online" in q
            or "search internet" in q
            or "look it up online" in q
            or "find online" in q
            or "browse the web" in q
            or "latest news" in q
            or "current news" in q
        )

        explicit_tool = (
            q.startswith("calculate ")
            or q.startswith("convert ")
            or q.startswith("set a reminder")
            or q.startswith("remind me")
            or q.startswith("what time is it")
            or q.startswith("what's the weather")
            or q.startswith("what is the weather")
        )

        knowledge_patterns = (
            "what is ",
            "what are ",
            "who is ",
            "who was ",
            "where is ",
            "where was ",
            "when was ",
            "when did ",
            "why is ",
            "why are ",
            "why was ",
            "why were ",
            "why do ",
            "why does ",
            "why did ",
            "how does ",
            "how do ",
            "how did ",
            "how is ",
            "how are ",
            "explain ",
            "tell me about ",
            "define ",
            "meaning of ",
            "what's ",
            "whats ",
        )

        if (
            not explicit_web
            and not explicit_tool
            and (
                q.startswith(knowledge_patterns)
                or q.endswith("?")
            )
        ):
            intent = Intent(
                name="Chat",
                confidence=0.94,
                requires_planning=False,
                requires_tools=False,
                requires_documents=False,
                requires_memory=False,
                requires_web=False,
                requires_reasoning=False,
                data={
                    "knowledge_query": True,
                    "action_name": None,
                    "action_params": {},
                },
            )

            self.intent_history.append(intent)

            if len(self.intent_history) > 100:
                self.intent_history.pop(0)

            return intent

        # Delegate to semantic analysis if LLM router is available  
        if self.llm_router and hasattr(self.llm_router, "chat"):  
            semantic_intent = await self._semantic_intent(query)  
            if semantic_intent is not None:  
                self.intent_history.append(semantic_intent)  
                if len(self.intent_history) > 100:  
                    self.intent_history.pop(0)  
                return semantic_intent  

        # Fallback local heuristics  
        if q in {"hi", "hello", "hey", "good morning", "good afternoon", "good evening"}:  
            intent = Intent("Chat", 0.99, False, False, False, False, False, False)  
            self.intent_history.append(intent)  
            if len(self.intent_history) > 100:  
                self.intent_history.pop(0)  
            return intent  

        intent = Intent(  
            name="Chat",  
            confidence=0.80,  
            requires_planning=False,  
            requires_tools=False,  
            requires_documents=False,  
            requires_memory=False,  
            requires_web=False,
            requires_reasoning=False,
        )  
        self.intent_history.append(intent)  
        if len(self.intent_history) > 100:  
            self.intent_history.pop(0)  
        return intent  

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
- requires_web (bool)
- requires_reasoning (bool)
- context_dependent (bool)
- knowledge_query (bool)
- confidence (float between 0.0 and 1.0)

IMPORTANT CLASSIFICATION RULES:

- Ordinary factual questions such as "What is DNA?",
  "What is photosynthesis?", "Explain TCP", or
  "How does replication work?" are Chat/knowledge requests.
- Do NOT classify ordinary knowledge questions as Web Search
  unless the user explicitly asks for current/latest/online information.
- If the question depends on the previous conversation,
  set context_dependent=true and requires_memory=true.
- Short follow-ups such as "Why is it important?",
  "How does it work?", "What about that?", and
  "Tell me more" are context-dependent.
- Do not invent an action_name.
- Return valid JSON only.

Return ONLY valid JSON in this exact structure:
{
  "intent": "CategoryName",
  "confidence": 0.95,
  "requires_planning": false,
  "requires_tools": false,
  "requires_documents": false,
  "requires_memory": false,
  "requires_web": false,
  "requires_reasoning": false,
  "context_dependent": false,
  "knowledge_query": false,
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

            allowed_intents = {
                "Chat",
                "Follow-up",
                "Memory",
                "Planning",
                "Research",
                "Coding",
                "Tool",
                "Document",
                "Web Search",
                "Multi-step task",
                "Clarification needed",
            }

            name = str(
                data.get("intent", "Chat")
            ).strip()

            if name not in allowed_intents:
                name = "Chat"

            confidence = float(data.get("confidence", 0.80))  
            requires_planning = bool(data.get("requires_planning", False))  
            requires_tools = bool(data.get("requires_tools", False))  
            requires_documents = bool(data.get("requires_documents", False))  
            requires_memory = bool(data.get("requires_memory", False))  
            requires_web = bool(data.get("requires_web", False))  
            requires_reasoning = bool(data.get("requires_reasoning", False))  
            context_dependent = bool(
                data.get("context_dependent", False)
            )
            knowledge_query = bool(
                data.get("knowledge_query", False)
            )

            return Intent(  
                name=name,  
                confidence=max(0.0, min(confidence, 1.0)),  
                requires_planning=requires_planning,  
                requires_tools=requires_tools,  
                requires_documents=requires_documents,  
                requires_memory=requires_memory,  
                requires_web=requires_web,
                requires_reasoning=requires_reasoning,
                data={  
                    "action_name": data.get("action_name"),  
                    "action_params": data.get("action_params", {}),  
                    "context_dependent": context_dependent,
                    "knowledge_query": knowledge_query,
                },  
            )  
        except Exception:  
            logger.exception("[IntentAnalyzer] Semantic intent classification failed.")  
            return None  

    def _normalize(self, query: str) -> str:  
        return re.sub(r"\s+", " ", str(query or "").lower()).strip()  

    def previous_intent(self):  
        if not self.intent_history:  
            return None  
        return self.intent_history[-1]
