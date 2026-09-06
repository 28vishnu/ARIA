from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
import logging
import re
import json
import copy


logger = logging.getLogger("aria")


class IntentName:
    """Canonical intent names used across ARIA's cognitive pipeline."""

    CHAT = "Chat"
    FOLLOW_UP = "Follow-up"
    MEMORY = "Memory"
    PLANNING = "Planning"
    RESEARCH = "Research"
    CODING = "Coding"
    TOOL = "Tool"
    DOCUMENT = "Document"
    WEB_SEARCH = "Web Search"
    MULTI_STEP = "Multi-step task"
    CLARIFICATION = "Clarification needed"
    VISION = "Vision"
    AUTOMATION = "Automation"


ALLOWED_INTENTS = {
    IntentName.CHAT,
    IntentName.FOLLOW_UP,
    IntentName.MEMORY,
    IntentName.PLANNING,
    IntentName.RESEARCH,
    IntentName.CODING,
    IntentName.TOOL,
    IntentName.DOCUMENT,
    IntentName.WEB_SEARCH,
    IntentName.MULTI_STEP,
    IntentName.CLARIFICATION,
    IntentName.VISION,
    IntentName.AUTOMATION,
}


@dataclass
class Intent:
    """
    Canonical structured intent contract.

    `name` remains the historical field used by the existing system.
    `intent_type` is the compatibility alias used by ReasoningEngine.
    """

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
        return self.name

    @property
    def context_dependent(self) -> bool:
        return bool(self.data.get("context_dependent", False))

    @property
    def knowledge_query(self) -> bool:
        return bool(self.data.get("knowledge_query", False))

    @property
    def action_name(self) -> Optional[str]:
        value = self.data.get("action_name")
        return str(value).strip() if value else None

    @property
    def action_params(self) -> Dict[str, Any]:
        value = self.data.get("action_params", {})
        return value if isinstance(value, dict) else {}


class IntentAnalyzer:
    """
    ARIA's canonical intent classification layer.

    Classification order:
      1. deterministic high-confidence signals
      2. explicit contextual/follow-up signals
      3. semantic LLM classification when appropriate
      4. safe Chat fallback

    This layer classifies the request only. It does not execute tools,
    agents, planners, memory operations, or web searches.

    The analyzer is deliberately conservative about current-information
    routing: ordinary factual questions remain Chat/knowledge requests
    unless current/online information is explicitly requested.
    """

    INTENT_VERSION = 2
    MAX_HISTORY = 100

    def __init__(self, llm_router=None):
        self.llm_router = llm_router
        self.intent_history: List[Intent] = []

    # ---------------------------------------------------------
    # Generic helpers
    # ---------------------------------------------------------

    @staticmethod
    def _normalize(query: Any) -> str:
        return re.sub(
            r"\s+",
            " ",
            str(query or "").lower(),
        ).strip()

    @staticmethod
    def _contains_any(text: str, phrases) -> bool:
        return any(str(phrase).lower() in text for phrase in phrases)

    @staticmethod
    def _safe_bool(value: Any, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value

        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "yes", "1", "on"}:
                return True
            if normalized in {"false", "no", "0", "off"}:
                return False

        return default

    @staticmethod
    def _safe_confidence(value: Any, default: float = 0.80) -> float:
        try:
            score = float(value)
        except (TypeError, ValueError):
            score = default

        return max(0.0, min(1.0, score))

    def _record(self, intent: Intent) -> Intent:
        intent.confidence = self._safe_confidence(intent.confidence)

        if not isinstance(intent.data, dict):
            intent.data = {}

        intent.data.setdefault("intent_version", self.INTENT_VERSION)

        # Keep history bounded and avoid retaining mutable references.
        self.intent_history.append(copy.deepcopy(intent))

        if len(self.intent_history) > self.MAX_HISTORY:
            del self.intent_history[:-self.MAX_HISTORY]

        return intent

    @staticmethod
    def _intent(
        name: str,
        confidence: float,
        *,
        requires_planning: bool = False,
        requires_tools: bool = False,
        requires_documents: bool = False,
        requires_memory: bool = False,
        requires_web: bool = False,
        requires_reasoning: bool = False,
        data: Optional[Dict[str, Any]] = None,
    ) -> Intent:
        return Intent(
            name=name,
            confidence=confidence,
            requires_planning=requires_planning,
            requires_tools=requires_tools,
            requires_documents=requires_documents,
            requires_memory=requires_memory,
            requires_web=requires_web,
            requires_reasoning=requires_reasoning,
            data=data or {},
        )

    # ---------------------------------------------------------
    # Deterministic signal detection
    # ---------------------------------------------------------

    def _is_explicit_web_request(self, q: str) -> bool:
        return self._contains_any(
            q,
            (
                "search the web",
                "search online",
                "search internet",
                "search the internet",
                "look it up online",
                "find online",
                "browse the web",
                "browse online",
                "search for this online",
                "google this",
                "look this up",
                "look it up",
                "on the internet",
            ),
        )

    def _is_current_information_request(self, q: str) -> bool:
        return self._contains_any(
            q,
            (
                "latest",
                "today",
                "current",
                "recent",
                "right now",
                "as of now",
                "this week",
                "this month",
                "news",
                "what happened",
                "current price",
                "current status",
                "live",
            ),
        )

    def _is_explicit_tool_request(self, q: str) -> bool:
        return (
            q.startswith("calculate ")
            or q.startswith("convert ")
            or q.startswith("set a reminder")
            or q.startswith("remind me")
            or q.startswith("what time is it")
            or q.startswith("what's the weather")
            or q.startswith("what is the weather")
            or q.startswith("check the weather")
        )

    def _is_mathematical_request(self, q: str) -> bool:
        if re.search(r"\d+\s*(?:[+\-*/×÷%])\s*\d+", q):
            return True

        return self._contains_any(
            q,
            (
                "calculate",
                "multiply",
                "divide",
                "subtract",
                "add",
                "plus",
                "minus",
                "times",
                "percentage of",
                "percent of",
            ),
        )

    def _is_follow_up(self, q: str) -> bool:
        exact = {
            "continue",
            "continue please",
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
            "what happens next",
            "what about this",
        }

        if q in exact:
            return True

        patterns = (
            r"^why\s+(?:is|are|was|were)\s+(?:it|this|that)\b",
            r"^why\s+does\s+(?:it|this|that)\b",
            r"^how\s+does\s+(?:it|this|that)\b",
            r"^how\s+is\s+(?:it|this|that)\b",
            r"^what\s+about\s+(?:it|this|that)\b",
            r"^tell\s+me\s+more\b",
            r"^explain\s+more\b",
            r"^continue\b",
            r"^go\s+on\b",
        )

        return any(
            re.search(pattern, q, flags=re.IGNORECASE)
            for pattern in patterns
        )

    def _is_memory_request(self, q: str) -> bool:
        return self._contains_any(
            q,
            (
                "remember",
                "do you remember",
                "what do you remember",
                "what did i say",
                "my name",
                "my favorite",
                "my favourite",
                "about me",
                "forget that",
                "forget this",
                "forget my",
                "delete memory",
                "remove memory",
                "save this",
                "store this",
                "remember this",
            ),
        )

    def _is_document_request(self, q: str) -> bool:
        return self._contains_any(
            q,
            (
                "document",
                "pdf",
                "file",
                "attachment",
                "uploaded file",
                "from the document",
                "in the document",
                "summarize this",
                "summarise this",
                "read this file",
            ),
        )

    def _is_coding_request(self, q: str) -> bool:
        return self._contains_any(
            q,
            (
                "code",
                "coding",
                "program",
                "programming",
                "python",
                "javascript",
                "typescript",
                "html",
                "css",
                "fastapi",
                "api",
                "github",
                "repository",
                "repo",
                "codebase",
                "debug",
                "bug",
                "refactor",
                "function",
                "class",
                "stack trace",
                "error in my code",
            ),
        )

    def _is_planning_request(self, q: str) -> bool:
        return self._contains_any(
            q,
            (
                "make me a plan",
                "create a plan",
                "plan for",
                "roadmap",
                "strategy",
                "schedule",
                "steps",
                "how should i",
                "what should i do",
                "step by step plan",
            ),
        ) or q == "plan"

    def _is_automation_request(self, q: str) -> bool:
        return self._contains_any(
            q,
            (
                "remind me",
                "set a reminder",
                "reminder",
                "every day",
                "every week",
                "every month",
                "automatically",
                "monitor",
                "notify me when",
                "let me know when",
                "schedule a notification",
            ),
        )

    def _is_vision_request(self, q: str) -> bool:
        return self._contains_any(
            q,
            (
                "image",
                "photo",
                "picture",
                "screenshot",
                "look at this",
                "what is in this image",
                "analyze this image",
                "analyse this image",
                "ocr",
            ),
        )

    def _is_knowledge_request(self, q: str) -> bool:
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

        return q.startswith(knowledge_patterns) or q.endswith("?")

    # ---------------------------------------------------------
    # Deterministic classification
    # ---------------------------------------------------------

    async def _deterministic(self, query: str) -> Optional[Intent]:
        q = self._normalize(query)

        if not q:
            return self._intent(
                IntentName.CHAT,
                0.50,
                requires_reasoning=False,
                data={
                    "knowledge_query": False,
                    "context_dependent": False,
                    "action_name": None,
                    "action_params": {},
                },
            )

        # Automation must precede generic "remind"/"schedule" handling.
        if self._is_automation_request(q):
            return self._intent(
                IntentName.AUTOMATION,
                0.99,
                requires_tools=True,
                requires_reasoning=True,
                data={
                    "action_name": "automation",
                    "action_params": {},
                    "context_dependent": False,
                    "knowledge_query": False,
                },
            )

        # Explicit calculator/tool requests.
        if self._is_mathematical_request(q):
            return self._intent(
                IntentName.TOOL,
                0.99,
                requires_tools=True,
                requires_reasoning=False,
                data={
                    "tool": "calculator",
                    "action_name": "calculator",
                    "action_params": {},
                    "context_dependent": False,
                    "knowledge_query": False,
                },
            )

        # Explicit online/current requests must not be swallowed by
        # generic knowledge-question detection.
        explicit_web = self._is_explicit_web_request(q)
        current = self._is_current_information_request(q)

        if explicit_web:
            return self._intent(
                IntentName.WEB_SEARCH,
                0.99,
                requires_tools=True,
                requires_web=True,
                requires_reasoning=True,
                data={
                    "action_name": "web_search",
                    "action_params": {},
                    "explicit_web": True,
                    "context_dependent": False,
                    "knowledge_query": False,
                },
            )

        if current:
            return self._intent(
                IntentName.RESEARCH,
                0.97,
                requires_tools=True,
                requires_web=True,
                requires_reasoning=True,
                data={
                    "action_name": "web_search",
                    "action_params": {},
                    "current_information": True,
                    "context_dependent": False,
                    "knowledge_query": False,
                },
            )

        # Vision before generic "what is..." handling.
        if self._is_vision_request(q):
            return self._intent(
                IntentName.VISION,
                0.98,
                requires_tools=True,
                requires_reasoning=True,
                data={
                    "action_name": "vision",
                    "action_params": {},
                    "context_dependent": False,
                    "knowledge_query": False,
                },
            )

        # Documents before generic questions.
        if self._is_document_request(q):
            return self._intent(
                IntentName.DOCUMENT,
                0.98,
                requires_documents=True,
                requires_tools=True,
                requires_reasoning=True,
                data={
                    "action_name": "document",
                    "action_params": {},
                    "context_dependent": False,
                    "knowledge_query": False,
                },
            )

        # Memory before generic personal questions.
        if self._is_memory_request(q):
            return self._intent(
                IntentName.MEMORY,
                0.99,
                requires_memory=True,
                requires_reasoning=False,
                data={
                    "action_name": "memory",
                    "action_params": {},
                    "context_dependent": False,
                    "knowledge_query": False,
                },
            )

        # Planning.
        if self._is_planning_request(q):
            return self._intent(
                IntentName.PLANNING,
                0.97,
                requires_planning=True,
                requires_reasoning=True,
                data={
                    "action_name": "planner",
                    "action_params": {},
                    "context_dependent": False,
                    "knowledge_query": False,
                },
            )

        # Coding before ordinary question fallback.
        if self._is_coding_request(q):
            return self._intent(
                IntentName.CODING,
                0.97,
                requires_tools=True,
                requires_reasoning=True,
                data={
                    "action_name": "coding",
                    "action_params": {},
                    "context_dependent": False,
                    "knowledge_query": False,
                },
            )

        # Follow-up is intentionally after explicit capability requests.
        if self._is_follow_up(q):
            return self._intent(
                IntentName.FOLLOW_UP,
                0.98,
                requires_memory=True,
                requires_reasoning=True,
                data={
                    "context_dependent": True,
                    "knowledge_query": False,
                    "action_name": None,
                    "action_params": {},
                },
            )

        # Ordinary factual questions remain Chat/knowledge requests.
        if self._is_knowledge_request(q):
            return self._intent(
                IntentName.CHAT,
                0.94,
                requires_reasoning=False,
                data={
                    "knowledge_query": True,
                    "context_dependent": False,
                    "action_name": None,
                    "action_params": {},
                },
            )

        # Explicit multi-step task language.
        if self._contains_any(
            q,
            (
                "do this for me",
                "handle this",
                "take care of this",
                "complete this task",
                "multi step",
                "multiple steps",
            ),
        ):
            return self._intent(
                IntentName.MULTI_STEP,
                0.90,
                requires_planning=True,
                requires_tools=True,
                requires_reasoning=True,
                data={
                    "action_name": None,
                    "action_params": {},
                    "context_dependent": False,
                    "knowledge_query": False,
                },
            )

        # Greeting.
        if q in {
            "hi",
            "hello",
            "hey",
            "good morning",
            "good afternoon",
            "good evening",
        }:
            return self._intent(
                IntentName.CHAT,
                0.99,
                requires_reasoning=False,
                data={
                    "knowledge_query": False,
                    "context_dependent": False,
                    "action_name": None,
                    "action_params": {},
                },
            )

        return None

    # ---------------------------------------------------------
    # Semantic classification
    # ---------------------------------------------------------

    @staticmethod
    def _strip_json_fence(value: Any) -> str:
        cleaned = str(value or "").strip()

        if cleaned.startswith("```"):
            cleaned = re.sub(
                r"^```(?:json)?\s*",
                "",
                cleaned,
                flags=re.IGNORECASE,
            )
            cleaned = re.sub(
                r"\s*```$",
                "",
                cleaned,
            ).strip()

        return cleaned

    def _semantic_system_prompt(self) -> str:
        return """
You are ARIA's semantic intent classifier.

Classify the user query into exactly one of:
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
- Vision
- Automation

Return ONLY valid JSON.

Rules:
1. Ordinary factual questions such as "What is DNA?",
   "What is photosynthesis?", "Explain TCP", and
   "How does replication work?" are Chat/knowledge requests.
2. Do NOT classify ordinary factual questions as Web Search or
   Research unless the user explicitly requests current/latest/online
   information or the wording clearly depends on changing information.
3. Short contextual follow-ups such as "Why is it important?",
   "How does it work?", "What about that?", and "Tell me more"
   are Follow-up and require memory/context.
4. Personal-memory requests are Memory.
5. Mathematical calculations or deterministic conversions are Tool.
6. Coding/debugging/repository requests are Coding.
7. Document/PDF/file requests are Document.
8. Multi-step strategies or roadmaps are Planning.
9. Reminders, monitoring, recurring notifications are Automation.
10. Image/photo/screenshot/OCR analysis is Vision.
11. Explicit online search is Web Search.
12. Do not invent action names. Use null unless a clear canonical
    action is implied.
13. Keep confidence between 0.0 and 1.0.

JSON schema:
{
  "intent": "Chat",
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

    def _normalize_semantic_result(self, data: Any) -> Optional[Intent]:
        if not isinstance(data, dict):
            return None

        name = str(data.get("intent", IntentName.CHAT)).strip()

        # Tolerate common model capitalization/spacing errors without
        # allowing arbitrary categories into the pipeline.
        aliases = {
            "chat": IntentName.CHAT,
            "follow up": IntentName.FOLLOW_UP,
            "follow-up": IntentName.FOLLOW_UP,
            "memory": IntentName.MEMORY,
            "planning": IntentName.PLANNING,
            "research": IntentName.RESEARCH,
            "coding": IntentName.CODING,
            "tool": IntentName.TOOL,
            "document": IntentName.DOCUMENT,
            "web search": IntentName.WEB_SEARCH,
            "multi-step task": IntentName.MULTI_STEP,
            "multi step task": IntentName.MULTI_STEP,
            "clarification needed": IntentName.CLARIFICATION,
            "vision": IntentName.VISION,
            "automation": IntentName.AUTOMATION,
        }

        canonical = aliases.get(name.lower(), name)

        if canonical not in ALLOWED_INTENTS:
            return None

        action_params = data.get("action_params", {})
        if not isinstance(action_params, dict):
            action_params = {}

        intent = self._intent(
            canonical,
            self._safe_confidence(data.get("confidence", 0.80)),
            requires_planning=self._safe_bool(
                data.get("requires_planning", False)
            ),
            requires_tools=self._safe_bool(
                data.get("requires_tools", False)
            ),
            requires_documents=self._safe_bool(
                data.get("requires_documents", False)
            ),
            requires_memory=self._safe_bool(
                data.get("requires_memory", False)
            ),
            requires_web=self._safe_bool(
                data.get("requires_web", False)
            ),
            requires_reasoning=self._safe_bool(
                data.get("requires_reasoning", False)
            ),
            data={
                "action_name": data.get("action_name"),
                "action_params": copy.deepcopy(action_params),
                "context_dependent": self._safe_bool(
                    data.get("context_dependent", False)
                ),
                "knowledge_query": self._safe_bool(
                    data.get("knowledge_query", False)
                ),
                "semantic": True,
            },
        )

        # Enforce important canonical invariants.
        if canonical == IntentName.FOLLOW_UP:
            intent.requires_memory = True
            intent.requires_reasoning = True
            intent.data["context_dependent"] = True

        if canonical in {
            IntentName.WEB_SEARCH,
            IntentName.RESEARCH,
        }:
            intent.requires_web = True
            intent.requires_tools = True

        if canonical == IntentName.MEMORY:
            intent.requires_memory = True

        if canonical == IntentName.DOCUMENT:
            intent.requires_documents = True
            intent.requires_tools = True

        if canonical == IntentName.CODING:
            intent.requires_reasoning = True

        if canonical == IntentName.PLANNING:
            intent.requires_planning = True
            intent.requires_reasoning = True

        if canonical == IntentName.VISION:
            intent.requires_tools = True
            intent.requires_reasoning = True

        if canonical == IntentName.AUTOMATION:
            intent.requires_tools = True
            intent.requires_reasoning = True

        return intent

    async def _semantic_intent(
        self,
        query: str,
    ) -> Optional[Intent]:
        if not self.llm_router:
            return None

        chat = getattr(self.llm_router, "chat", None)
        if not callable(chat):
            return None

        try:
            response = await chat(
                messages=[
                    {
                        "role": "system",
                        "content": self._semantic_system_prompt(),
                    },
                    {
                        "role": "user",
                        "content": query,
                    },
                ],
                temperature=0.0,
                max_tokens=250,
            )

            if not isinstance(response, str) or not response.strip():
                return None

            cleaned = self._strip_json_fence(response)

            # Prefer strict JSON first.
            try:
                data = json.loads(cleaned)
            except json.JSONDecodeError:
                # Recover a single JSON object if the provider added
                # harmless surrounding prose.
                match = re.search(
                    r"\{.*\}",
                    cleaned,
                    flags=re.DOTALL,
                )
                if not match:
                    return None
                data = json.loads(match.group(0))

            return self._normalize_semantic_result(data)

        except Exception:
            logger.exception(
                "[IntentAnalyzer] Semantic intent classification failed."
            )
            return None

    # ---------------------------------------------------------
    # Public analysis
    # ---------------------------------------------------------

    async def analyze(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Intent:
        """
        Analyze one request.

        Context is accepted for Phase 11 compatibility. The analyzer uses
        only lightweight contextual hints and never mutates the supplied
        dictionary.
        """
        context = context if isinstance(context, dict) else {}
        q = self._normalize(query)

        deterministic = await self._deterministic(query)

        if deterministic is not None:
            return self._record(deterministic)

        # If the caller explicitly says the request is contextual, preserve
        # that signal before asking an LLM to classify it.
        contextual_hint = bool(
            context.get("conversation", {}).get("looks_like_follow_up")
            if isinstance(context.get("conversation"), dict)
            else False
        )

        if contextual_hint and self._is_follow_up(q):
            return self._record(
                self._intent(
                    IntentName.FOLLOW_UP,
                    0.98,
                    requires_memory=True,
                    requires_reasoning=True,
                    data={
                        "context_dependent": True,
                        "knowledge_query": False,
                        "action_name": None,
                        "action_params": {},
                    },
                )
            )

        semantic = await self._semantic_intent(query)

        if semantic is not None:
            # Safety normalization: explicit current/online language in the
            # actual request must not be downgraded by a semantic response.
            if self._is_explicit_web_request(q):
                semantic.name = IntentName.WEB_SEARCH
                semantic.requires_web = True
                semantic.requires_tools = True
                semantic.data["action_name"] = (
                    semantic.data.get("action_name") or "web_search"
                )

            elif self._is_current_information_request(q):
                semantic.name = IntentName.RESEARCH
                semantic.requires_web = True
                semantic.requires_tools = True
                semantic.requires_reasoning = True
                semantic.data["action_name"] = (
                    semantic.data.get("action_name") or "web_search"
                )

            return self._record(semantic)

        # Safe fallback.
        if q in {
            "hi",
            "hello",
            "hey",
            "good morning",
            "good afternoon",
            "good evening",
        }:
            return self._record(
                self._intent(
                    IntentName.CHAT,
                    0.99,
                    requires_reasoning=False,
                    data={
                        "knowledge_query": False,
                        "context_dependent": False,
                        "action_name": None,
                        "action_params": {},
                    },
                )
            )

        return self._record(
            self._intent(
                IntentName.CHAT,
                0.80,
                requires_reasoning=False,
                data={
                    "knowledge_query": False,
                    "context_dependent": False,
                    "action_name": None,
                    "action_params": {},
                },
            )
        )

    def previous_intent(self) -> Optional[Intent]:
        if not self.intent_history:
            return None
        return copy.deepcopy(self.intent_history[-1])
