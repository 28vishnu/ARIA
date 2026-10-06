from __future__ import annotations

"""Canonical master-request understanding layer for ARIA.

Step 1 establishes one deterministic admission contract before the rest of
CognitiveCore decides how a request is executed.  This module does not perform
side effects.  It only normalizes the complete incoming request and determines
its high-level mode, constraints, and execution intent.
"""

from dataclasses import dataclass, field
import re
from typing import Any, Mapping


class JarvisRequestMode:
    ANSWER = "answer"
    RESEARCH = "research"
    PLAN = "plan"
    TOOL = "tool"
    DOCUMENT = "document"
    VISION = "vision"
    ENGINEERING = "engineering"
    AUTOMATION = "automation"
    MEMORY = "memory"
    CONVERSATION = "conversation"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class JarvisRequest:
    """Immutable normalized representation of one master request."""

    request_id: str
    text: str
    mode: str
    confidence: float
    requires_execution: bool
    read_only: bool
    asks_for_phases_only: bool
    asks_for_analysis_only: bool
    asks_for_answer_only: bool
    explicit_no_mutation: bool
    explicit_authorization: bool
    engineering_intent: bool
    research_intent: bool
    tool_intent: bool
    memory_intent: bool
    document_intent: bool
    vision_intent: bool
    automation_intent: bool
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "text": self.text,
            "mode": self.mode,
            "confidence": self.confidence,
            "requires_execution": self.requires_execution,
            "read_only": self.read_only,
            "asks_for_phases_only": self.asks_for_phases_only,
            "asks_for_analysis_only": self.asks_for_analysis_only,
            "asks_for_answer_only": self.asks_for_answer_only,
            "explicit_no_mutation": self.explicit_no_mutation,
            "explicit_authorization": self.explicit_authorization,
            "engineering_intent": self.engineering_intent,
            "research_intent": self.research_intent,
            "tool_intent": self.tool_intent,
            "memory_intent": self.memory_intent,
            "document_intent": self.document_intent,
            "vision_intent": self.vision_intent,
            "automation_intent": self.automation_intent,
            "metadata": dict(self.metadata),
        }


class JarvisRequestKernel:
    """Canonical, side-effect-free request understanding kernel.

    The kernel deliberately does not call an LLM, tool, GitHub, filesystem,
    deployment service, or engineering executor.  It creates a stable request
    contract that downstream systems can consume without re-parsing the master
    message differently.
    """

    VERSION = "ARIA-JARVIS-REQUEST-KERNEL-20261006.1"

    _PHASE_PATTERNS = (
        r"\bphases?\b",
        r"\bstep(?:s)?\b",
        r"\broadmap\b",
        r"\barchitecture\b",
        r"\bplan\b",
        r"\bdesign\b",
        r"\bhow should we\b",
        r"\bwhat should we do\b",
    )

    _ANALYSIS_PATTERNS = (
        r"\banaly[sz]e\b",
        r"\banalysis\b",
        r"\binspect\b",
        r"\breview\b",
        r"\baudit\b",
        r"\bcheck\b",
        r"\bexplain\b",
        r"\bunderstand\b",
    )

    _NO_MUTATION_PATTERNS = (
        r"\bdo not\s+(?:modify|change|create|delete|write|repair|implement)\b",
        r"\bdon't\s+(?:modify|change|create|delete|write|repair|implement)\b",
        r"\bwithout\s+(?:modif(?:y|ying)|chang(?:e|ing)|creat(?:e|ing)|delet(?:e|ing)|writ(?:e|ing)|implement(?:ing))\b",
        r"\bread[- ]only\b",
        r"\bno\s+(?:changes?|modifications?|writes?|mutations?)\b",
        r"\bdo not\s+commit\b",
        r"\bdo not\s+push\b",
        r"\bdo not\s+deploy\b",
    )

    _AUTHORIZATION_PATTERNS = (
        r"\bI\s+(?:authorize|authorise|approve)\b",
        r"\byou\s+(?:may|can)\s+(?:push|deploy|commit)\b",
        r"\bpush\s+to\s+github\b",
        r"\bdeploy\s+(?:it|this|the)\b",
        r"\bgo\s+ahead\s+and\s+(?:implement|modify|change|deploy|push)\b",
    )

    _ENGINEERING_TERMS = (
        "code", "coding", "program", "programming", "software",
        "repository", "repo", "github", "git", "implement",
        "implementation", "develop", "development", "developer",
        "build", "bug", "debug", "refactor", "feature", "api",
        "backend", "frontend", "architecture", "deployment", "deploy",
        "test the code", "write code", "modify the code", "create a file",
        "modify a file", "engineering", "developer", "autonomous ai",
    )

    _RESEARCH_TERMS = (
        "research", "search the web", "search online", "look up",
        "find information", "investigate", "compare", "latest", "current",
        "sources", "documentation", "papers", "news",
    )

    _TOOL_TERMS = (
        "calculate", "calculator", "convert", "download", "upload", "send",
        "open", "close", "run", "execute", "schedule", "remind", "notify",
        "create a file", "read a file", "edit a file",
    )

    _MEMORY_TERMS = (
        "remember", "memorize", "save this", "store this", "don't forget",
        "do you remember", "what did i tell you", "what do you know about me",
    )

    _DOCUMENT_TERMS = (
        "document", "pdf", "docx", "spreadsheet", "xlsx", "presentation",
        "pptx", "report", "letter", "resume",
    )

    _VISION_TERMS = (
        "image", "photo", "picture", "screenshot", "vision", "look at this",
        "what is in this image", "analyze this image",
    )

    _AUTOMATION_TERMS = (
        "every day", "every morning", "every week", "remind me", "schedule",
        "monitor", "watch for", "notify me when", "recurring",
    )

    _ANSWER_TERMS = (
        "what is", "what are", "why", "how does", "how do", "explain",
        "difference between", "define", "meaning of", "tell me about",
    )

    def __init__(self) -> None:
        self.version = self.VERSION

    def understand(
        self,
        text: str,
        *,
        request_id: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> JarvisRequest:
        original = "" if text is None else str(text)
        normalized = " ".join(original.strip().split())
        lowered = normalized.casefold()
        request_id = str(request_id or "").strip() or "unassigned"

        flags = {
            "engineering": self._contains_any(lowered, self._ENGINEERING_TERMS),
            "research": self._contains_any(lowered, self._RESEARCH_TERMS),
            "tool": self._contains_any(lowered, self._TOOL_TERMS),
            "memory": self._contains_any(lowered, self._MEMORY_TERMS),
            "document": self._contains_any(lowered, self._DOCUMENT_TERMS),
            "vision": self._contains_any(lowered, self._VISION_TERMS),
            "automation": self._contains_any(lowered, self._AUTOMATION_TERMS),
        }

        phases_only = self._contains_pattern(lowered, self._PHASE_PATTERNS) and (
            self._contains_pattern(lowered, self._ANALYSIS_PATTERNS)
            or any(word in lowered for word in ("only", "just", "without implementing"))
            or not self._contains_any(lowered, ("implement", "write code", "modify the code", "change the code"))
        )
        analysis_only = self._contains_pattern(lowered, self._ANALYSIS_PATTERNS) and self._contains_pattern(lowered, self._NO_MUTATION_PATTERNS)
        answer_only = any(lowered.startswith(prefix) for prefix in self._ANSWER_TERMS)
        explicit_no_mutation = self._contains_pattern(lowered, self._NO_MUTATION_PATTERNS)
        explicit_authorization = self._contains_pattern(lowered, self._AUTHORIZATION_PATTERNS)

        # Explicit constraints always outrank inferred execution intent.
        if phases_only:
            mode = JarvisRequestMode.PLAN
            confidence = 0.98
        elif flags["memory"] and not flags["engineering"]:
            mode = JarvisRequestMode.MEMORY
            confidence = 0.96
        elif flags["vision"]:
            mode = JarvisRequestMode.VISION
            confidence = 0.94
        elif flags["document"] and not flags["engineering"]:
            mode = JarvisRequestMode.DOCUMENT
            confidence = 0.93
        elif flags["automation"] and not flags["engineering"]:
            mode = JarvisRequestMode.AUTOMATION
            confidence = 0.92
        elif flags["research"] and not flags["engineering"]:
            mode = JarvisRequestMode.RESEARCH
            confidence = 0.92
        elif flags["tool"] and not flags["engineering"]:
            mode = JarvisRequestMode.TOOL
            confidence = 0.90
        elif flags["engineering"]:
            mode = JarvisRequestMode.ENGINEERING
            confidence = 0.98
        elif answer_only or normalized:
            mode = JarvisRequestMode.ANSWER
            confidence = 0.80
        else:
            mode = JarvisRequestMode.UNKNOWN
            confidence = 0.0

        requires_execution = mode in {
            JarvisRequestMode.TOOL,
            JarvisRequestMode.DOCUMENT,
            JarvisRequestMode.AUTOMATION,
            JarvisRequestMode.ENGINEERING,
        }

        # Planning/analysis/read-only constraints are never execution requests.
        if phases_only or analysis_only or explicit_no_mutation:
            requires_execution = False

        if mode == JarvisRequestMode.ENGINEERING and explicit_no_mutation:
            # Engineering remains the domain, but the downstream request must
            # be handled as inspection/planning rather than implementation.
            requires_execution = False

        return JarvisRequest(
            request_id=request_id,
            text=original,
            mode=mode,
            confidence=confidence,
            requires_execution=requires_execution,
            read_only=bool(explicit_no_mutation or phases_only or analysis_only),
            asks_for_phases_only=phases_only,
            asks_for_analysis_only=analysis_only,
            asks_for_answer_only=answer_only,
            explicit_no_mutation=explicit_no_mutation,
            explicit_authorization=explicit_authorization,
            engineering_intent=flags["engineering"],
            research_intent=flags["research"],
            tool_intent=flags["tool"],
            memory_intent=flags["memory"],
            document_intent=flags["document"],
            vision_intent=flags["vision"],
            automation_intent=flags["automation"],
            metadata=dict(metadata or {}),
        )

    @staticmethod
    def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
        return any(term in text for term in terms)

    @staticmethod
    def _contains_pattern(text: str, patterns: tuple[str, ...]) -> bool:
        return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


__all__ = [
    "JarvisRequest",
    "JarvisRequestKernel",
    "JarvisRequestMode",
]
