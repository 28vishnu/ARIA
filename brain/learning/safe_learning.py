"""Conservative gate for optional user-derived learning signals.

This module deliberately does not write to a database. It rejects obvious
secrets and highly sensitive content, and requires explicit opt-in before a
caller can retain a user-provided preference or fact.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

MAX_LEARNING_TEXT_CHARS = 2000

_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|passwd|secret)\s*[:=]\s*\S+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),  # SSN-like identifier
    re.compile(r"\b\d{12,19}\b"),  # long numeric account/card-like strings
)
_SENSITIVE_TERMS = re.compile(
    r"(?i)\b(diagnosed with|my medical condition|my religion is|my political party is|"
    r"my sexual orientation is|my password is|my private key is)\b"
)

@dataclass(frozen=True)
class LearningDecision:
    allowed: bool
    reason: str
    text: str = ""


def evaluate_learning_candidate(text: object, *, explicit_opt_in: bool = False) -> LearningDecision:
    """Assess a candidate before persistent learning; default is deny."""
    candidate = str(text or "").strip()
    if not candidate:
        return LearningDecision(False, "empty")
    if not explicit_opt_in:
        return LearningDecision(False, "explicit_opt_in_required")
    if len(candidate) > MAX_LEARNING_TEXT_CHARS:
        return LearningDecision(False, "too_long")
    if any(pattern.search(candidate) for pattern in _SECRET_PATTERNS):
        return LearningDecision(False, "possible_secret_or_identifier")
    if _SENSITIVE_TERMS.search(candidate):
        return LearningDecision(False, "sensitive_personal_content")
    # Do not turn arbitrary user text into executable instructions or rules.
    if re.search(r"(?i)\b(ignore all previous instructions|reveal system prompt|disable safety)\b", candidate):
        return LearningDecision(False, "instruction_injection_like_content")
    return LearningDecision(True, "approved_by_policy", candidate)
