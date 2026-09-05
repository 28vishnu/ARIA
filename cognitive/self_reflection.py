"""
ARIA Self-Reflection Engine
---------------------------
Phase 10 / Step 2

Provides a lightweight, dependency-free reflection layer for ARIA.

Responsibilities:
- Evaluate task outcomes and responses.
- Detect explicit failures, weak outcomes, and missing information.
- Record structured reflection events.
- Identify repeated failure patterns.
- Produce actionable improvement suggestions.
- Remain safe to call from synchronous or asynchronous orchestration code.

This module does not modify ARIA's core reasoning by itself. It produces
structured reflection data that the CognitiveCore/bootstrap layer can consume.
"""

from __future__ import annotations

import asyncio
import re
import time
import uuid
from collections import Counter, deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Deque, Dict, Iterable, List, Optional


@dataclass
class ReflectionEvent:
    """A single structured self-reflection record."""

    event_id: str
    timestamp: str
    task_id: Optional[str]
    session_id: Optional[str]
    success: bool
    score: float
    task: str
    response: str
    failure_type: Optional[str] = None
    observations: List[str] = field(default_factory=list)
    improvements: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class SelfReflectionEngine:
    """
    ARIA's bounded self-reflection and improvement engine.

    The engine deliberately avoids unrestricted self-modification. It records
    observations and recommendations rather than changing source code,
    permissions, credentials, or safety controls.
    """

    FAILURE_PATTERNS = {
        "timeout": (
            "timeout",
            "timed out",
            "deadline exceeded",
            "took too long",
        ),
        "provider_failure": (
            "provider unavailable",
            "all providers failed",
            "429",
            "rate limit",
            "service unavailable",
        ),
        "tool_failure": (
            "tool failed",
            "tool error",
            "execution failed",
            "action failed",
        ),
        "missing_information": (
            "not enough information",
            "insufficient information",
            "missing information",
            "need more information",
            "cannot determine",
        ),
        "permission": (
            "permission denied",
            "not authorized",
            "unauthorized",
            "access denied",
        ),
        "invalid_input": (
            "invalid input",
            "invalid request",
            "malformed request",
            "bad request",
        ),
    }

    FAILURE_PHRASES = (
        "i don't know",
        "i do not know",
        "i can't",
        "i cannot",
        "unable to",
        "couldn't",
        "could not",
        "failed to",
        "error occurred",
    )

    def __init__(
        self,
        max_history: int = 200,
        repeated_failure_threshold: int = 3,
    ) -> None:
        self.max_history = max(10, int(max_history))
        self.repeated_failure_threshold = max(2, int(repeated_failure_threshold))
        self._history: Deque[ReflectionEvent] = deque(maxlen=self.max_history)
        self._failure_counter: Counter[str] = Counter()
        self._lock = asyncio.Lock()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _text(value: Any, limit: int = 12000) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        return text[:limit]

    @staticmethod
    def _clamp_score(value: Any, default: float = 0.5) -> float:
        try:
            score = float(value)
        except (TypeError, ValueError):
            score = default
        return max(0.0, min(1.0, score))

    def _detect_failure_type(
        self,
        task: str,
        response: str,
        metadata: Dict[str, Any],
    ) -> Optional[str]:
        explicit = metadata.get("failure_type")
        if explicit:
            return self._text(explicit, 120)

        combined = f"{task}\n{response}".lower()

        for failure_type, patterns in self.FAILURE_PATTERNS.items():
            if any(pattern in combined for pattern in patterns):
                return failure_type

        return None

    def _observe(
        self,
        task: str,
        response: str,
        success: bool,
        score: float,
        failure_type: Optional[str],
        metadata: Dict[str, Any],
    ) -> List[str]:
        observations: List[str] = []

        if not task:
            observations.append("The task description was empty or unavailable.")

        if not response:
            observations.append("No usable response was produced.")

        if not success:
            observations.append("The task outcome was marked unsuccessful.")

        if score < 0.4:
            observations.append("The outcome quality score was low.")
        elif score < 0.7:
            observations.append("The outcome was only partially satisfactory.")

        if failure_type:
            observations.append(f"Detected failure category: {failure_type}.")

        latency = metadata.get("latency_ms")
        try:
            if latency is not None and float(latency) > 15000:
                observations.append("The operation had relatively high latency.")
        except (TypeError, ValueError):
            pass

        if metadata.get("retry_count", 0):
            observations.append(
                f"The operation required {metadata['retry_count']} retry attempt(s)."
            )

        return observations

    def _suggest(
        self,
        failure_type: Optional[str],
        observations: Iterable[str],
        metadata: Dict[str, Any],
    ) -> List[str]:
        suggestions: List[str] = []

        mapping = {
            "timeout": "Use tighter tool timeouts, bounded retries, and a fallback path.",
            "provider_failure": "Prefer provider health checks, cooldown-aware routing, and a fallback provider.",
            "tool_failure": "Validate tool inputs and capture the tool's structured error before retrying.",
            "missing_information": "Ask for the smallest missing detail or use available context before proceeding.",
            "permission": "Verify authorization and required permissions before attempting the operation again.",
            "invalid_input": "Validate and normalize inputs before dispatching the request.",
        }

        if failure_type in mapping:
            suggestions.append(mapping[failure_type])

        if metadata.get("retry_count", 0):
            suggestions.append("Avoid blind retries; use bounded retries with backoff.")

        if any("low" in item.lower() for item in observations):
            suggestions.append("Improve answer verification before returning the final result.")

        if not suggestions:
            suggestions.append("Continue monitoring the outcome and retain successful behavior.")

        # Preserve order while removing duplicates.
        return list(dict.fromkeys(suggestions))

    def reflect(
        self,
        task: str,
        response: str,
        success: Optional[bool] = None,
        score: Optional[float] = None,
        *,
        task_id: Optional[str] = None,
        session_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Reflect on one completed task and return a JSON-serializable report.
        """
        meta = dict(metadata or {})
        task_text = self._text(task)
        response_text = self._text(response)

        detected_failure = self._detect_failure_type(task_text, response_text, meta)

        if success is None:
            lowered = response_text.lower()
            success = not (
                detected_failure
                or any(phrase in lowered for phrase in self.FAILURE_PHRASES)
                or not response_text
            )

        final_score = self._clamp_score(
            score,
            default=0.85 if success else 0.25,
        )

        failure_type = detected_failure if not success or detected_failure else None
        observations = self._observe(
            task_text,
            response_text,
            bool(success),
            final_score,
            failure_type,
            meta,
        )
        improvements = self._suggest(failure_type, observations, meta)

        event = ReflectionEvent(
            event_id=uuid.uuid4().hex,
            timestamp=self._now(),
            task_id=task_id,
            session_id=session_id,
            success=bool(success),
            score=final_score,
            task=task_text,
            response=response_text,
            failure_type=failure_type,
            observations=observations,
            improvements=improvements,
            metadata=meta,
        )

        self._history.append(event)

        if failure_type:
            self._failure_counter[failure_type] += 1

        repeated = (
            failure_type is not None
            and self._failure_counter[failure_type]
            >= self.repeated_failure_threshold
        )

        if repeated:
            improvements.append(
                f"Repeated '{failure_type}' failures detected; review the responsible workflow."
            )

        return {
            "ok": True,
            "event": asdict(event),
            "repeated_failure": repeated,
            "failure_count": (
                self._failure_counter.get(failure_type, 0)
                if failure_type
                else 0
            ),
        }

    async def reflect_async(
        self,
        task: str,
        response: str,
        success: Optional[bool] = None,
        score: Optional[float] = None,
        *,
        task_id: Optional[str] = None,
        session_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Async-safe wrapper for orchestration code."""
        async with self._lock:
            return self.reflect(
                task,
                response,
                success,
                score,
                task_id=task_id,
                session_id=session_id,
                metadata=metadata,
            )

    def history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Return the newest reflection records first."""
        limit = max(1, min(int(limit), self.max_history))
        items = list(self._history)[-limit:]
        items.reverse()
        return [asdict(item) for item in items]

    def get_repeated_failures(self) -> Dict[str, int]:
        """Return failure categories that have reached the repetition threshold."""
        return {
            name: count
            for name, count in self._failure_counter.items()
            if count >= self.repeated_failure_threshold
        }

    def status(self) -> Dict[str, Any]:
        """Return a compact health/status snapshot."""
        total = len(self._history)
        successful = sum(1 for event in self._history if event.success)

        return {
            "available": True,
            "history_size": total,
            "max_history": self.max_history,
            "success_rate": (successful / total) if total else None,
            "failure_counts": dict(self._failure_counter),
            "repeated_failures": self.get_repeated_failures(),
        }

    def clear(self) -> None:
        """Clear bounded in-memory reflection state."""
        self._history.clear()
        self._failure_counter.clear()


# Compatibility aliases for simple imports.
SelfReflection = SelfReflectionEngine
ReflectionEngine = SelfReflectionEngine


__all__ = [
    "ReflectionEvent",
    "SelfReflectionEngine",
    "SelfReflection",
    "ReflectionEngine",
]
