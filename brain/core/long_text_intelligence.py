"""Lossless structural analysis for long user-provided text."""
from __future__ import annotations
from dataclasses import asdict, dataclass
import hashlib
import re
from typing import Any

_HEADING = re.compile(r"(?m)^\s*(?:#{1,6}\s+.+|\d+(?:\.\d+)*[.)]?\s+.{2,}|[A-Z][A-Z0-9 /&()_-]{3,})\s*$")
_URL = re.compile(r"https?://[^\s<>]+", re.I)
_PATH = re.compile(r"""(?<![\w.-])(?:[A-Za-z]:[\\/]|/|\.\.?/)[^\s`<>"']+""")

@dataclass(frozen=True)
class TextSegment:
    index: int
    start: int
    end: int
    text: str
    kind: str

def analyze_long_text(text: str, *, segment_chars: int = 6000) -> dict[str, Any]:
    """Index every character without dropping content; prefer paragraph boundaries."""
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if segment_chars < 256:
        raise ValueError("segment_chars must be at least 256")
    headings = tuple(m.group(0).strip() for m in _HEADING.finditer(text))
    segments: list[TextSegment] = []
    start, n = 0, len(text)
    while start < n:
        target, end = min(n, start + segment_chars), min(n, start + segment_chars)
        if target < n:
            boundary = text.rfind("\n\n", start + segment_chars // 2, target)
            if boundary < 0:
                boundary = text.rfind("\n", start + segment_chars // 2, target)
            if boundary > start:
                end = boundary + (2 if text[boundary:boundary+2] == "\n\n" else 1)
        piece = text[start:end]
        kind = "code" if piece.count("```") % 2 == 1 or re.search(r"(?m)^\s{4,}\S", piece) else "text"
        segments.append(TextSegment(len(segments), start, end, piece, kind))
        start = end
    if not segments:
        segments.append(TextSegment(0, 0, 0, "", "text"))
    return {
        "character_count": n, "word_count": len(re.findall(r"\S+", text)),
        "line_count": 0 if not text else text.count("\n") + 1,
        "paragraph_count": len([x for x in re.split(r"\n\s*\n", text) if x.strip()]),
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "complete": "".join(x.text for x in segments) == text, "truncated": False,
        "contains_code": bool(re.search(r"```|^\s{4,}\S", text, re.MULTILINE)),
        "contains_urls": bool(_URL.search(text)), "contains_paths": bool(_PATH.search(text)),
        "headings": headings, "segments": [asdict(x) for x in segments],
    }

def split_telegram_text(text: str, limit: int = 3800) -> list[str]:
    """Split long responses under Telegram's message limit, preserving content."""
    text = str(text or "")
    if limit < 100:
        raise ValueError("limit must be at least 100")
    if not text:
        return [""]
    chunks = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit + 1)
        if cut < limit // 2:
            cut = text.rfind(" ", 0, limit + 1)
        if cut < limit // 2:
            cut = limit
        chunks.append(text[:cut])
        text = text[cut:]
    if text or not chunks:
        chunks.append(text)
    return chunks
