"""Deterministic query planning for source-backed general knowledge retrieval.

No LLM, remote generation, or external service is used here. Long pasted context is
kept by the caller; this module derives a compact search query from the user's
explicit question or instruction at the end of that context.
"""
from __future__ import annotations

import re
from typing import Iterable

_DIRECTIVE_START = re.compile(
    r"(?i)\b(?:my question is|question:|please explain|explain|define|describe|"
    r"summari[sz]e|what is|what are|who is|who are|why does|why do|why is|"
    r"how does|how do|how is|how are|compare|difference between|find out|"
    r"look up|search for|tell me about)\b"
)
_STOP = {
    "what", "which", "who", "when", "where", "why", "how", "does", "do", "is", "are",
    "was", "were", "the", "a", "an", "and", "or", "to", "of", "for", "in", "on", "at",
    "with", "about", "please", "explain", "describe", "define", "tell", "me", "my", "your",
    "this", "that", "these", "those", "from", "into", "using", "based", "above", "below",
    "following", "text", "content", "document", "given", "provide", "give", "include", "show",
    "source", "sources", "url", "urls", "citation", "citations", "answer", "question", "simple",
    "words", "terms", "detail", "briefly", "brief", "example", "examples", "summarize", "summary",
}

def plan_knowledge_query(text: str, max_chars: int = 180) -> str:
    """Return a concise search query, preferring the explicit task near the end."""
    raw = str(text or "").strip()
    if not raw:
        return ""
    normalized = re.sub(r"\s+", " ", raw).replace("’", "'")

    # If a user pasted a long document and then asks a question, use that question
    # for retrieval rather than sending the entire document as search keywords.
    # Explicit task markers are the strongest signal, even when the preceding
    # document is thousands of characters long and occupies the same paragraph.
    marked = list(re.finditer(r"(?i)(?:^|\n)\s*(?:question|task|request)\s*:\s*(.+?)(?=\n|$)", raw))
    if marked:
        normalized = re.sub(r"\s+", " ", marked[-1].group(1)).strip()

    tail = normalized[-2400:]
    candidates = []
    for match in re.finditer(r"[^?!.]{3,240}\?", tail):
        candidate = match.group(0).strip(" \t\r\n.,;:-")
        if _DIRECTIVE_START.search(candidate):
            candidates.append(candidate)
    if candidates:
        normalized = candidates[-1]
    elif not marked:
        # Prefer the final explicit task line when it follows a pasted block.
        lines = [re.sub(r"\s+", " ", line).strip() for line in raw.splitlines() if line.strip()]
        if len(lines) > 1:
            for line in reversed(lines[-12:]):
                if len(line) <= 500 and _DIRECTIVE_START.search(line):
                    normalized = line
                    break

    normalized = re.sub(r"(?i)^\s*(?:my question is|question:)\s*", "", normalized)
    normalized = re.sub(r"(?i)\b(?:and\s+)?(?:provide|give|include|show)\s+(?:me\s+)?(?:the\s+)?(?:source(?:\s+urls?)?|urls?|citations?)\b.*$", "", normalized)
    normalized = re.sub(r"(?i)\b(?:and\s+)?(?:give|provide|include|show)\s+(?:me\s+)?(?:an?\s+)?(?:everyday\s+|real[- ]life\s+|simple\s+)?(?:example|examples|source|sources|citations?)\b.*$", "", normalized)
    normalized = re.sub(r"(?i)\b(?:in simple words|in simple terms|in easy words|for beginners|in detail|in brief|briefly|in short)\b.*$", "", normalized)
    normalized = re.sub(r"(?i)^\s*(?:please\s+)?(?:can you\s+)?(?:explain|define|describe|summari[sz]e|tell me about|what is|what are|who is|who are|why does|why do|why is|how does|how do|how is|how are|compare|difference between|find out|look up|search for)\s+", "", normalized)
    normalized = normalized.strip(" \t\r\n.,;:!?-–—")

    if len(normalized) <= max_chars:
        return normalized

    # For an unusually long task sentence, keep meaningful topic terms in order.
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9_+#.-]*", normalized)
    selected = [word for word in words if len(word) > 2 and word.casefold() not in _STOP]
    compact = " ".join(selected)
    if compact:
        return compact[:max_chars].rsplit(" ", 1)[0] or compact[:max_chars]
    return normalized[:max_chars].rsplit(" ", 1)[0] or normalized[:max_chars]
