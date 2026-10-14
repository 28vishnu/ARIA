"""Deterministic cleaning and validation for source-backed ARIA evidence.

This module never generates facts. It removes common HTML chrome, repeated
snippets, and obvious promotional/navigation text before evidence is indexed or
composed into an answer.
"""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from typing import Any, Iterable, List

_BLOCKED_TAGS = {
    "script", "style", "nav", "header", "footer", "aside", "form",
    "button", "noscript", "svg", "iframe", "dialog", "template",
}
_VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}
_BLOCKED_ATTR = re.compile(
    r"(?:^|[\s_-])(?:nav(?:igation)?|menu|newsletter|advert(?:isement)?|"
    r"promo(?:tion)?|cookie|subscribe|subscription|social|breadcrumb|"
    r"related|sidebar|paywall|modal|popup|account-menu)(?:$|[\s_-])",
    re.IGNORECASE,
)
_BOILERPLATE = re.compile(
    r"(?i)(?:explore your membership perks|never miss a discovery|"
    r"choose your newsletters|sign out|jump to:?|get the .*? newsletter|"
    r"by submitting your information|terms\s*&\s*conditions|privacy policy|"
    r"aged 16 or over|subscribe to our newsletter|sign up for our newsletter|"
    r"accept all cookies|manage cookie preferences|enable javascript to view|"
    r"skip to (?:content|main content)|related articles|related stories|"
    r"advertisement|sponsored content|all rights reserved|log in|login|"
    r"create an account|membership perks|newsletter sign[- ]?up|"
    r"table of contents|additional resources\s*$|frequently asked questions\s*$)"
)


class _ReadableHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: List[str] = []
        self.skip_stack: List[str] = []

    @staticmethod
    def _blocked(tag: str, attrs: list[tuple[str, str | None]]) -> bool:
        if tag.lower() in _BLOCKED_TAGS:
            return True
        values = dict(attrs)
        role = str(values.get("role") or "")
        identity = " ".join((str(values.get("id") or ""), str(values.get("class") or ""), role))
        return bool(_BLOCKED_ATTR.search(identity))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if self.skip_stack:
            if tag not in _VOID_TAGS:
                self.skip_stack.append(tag)
            return
        if self._blocked(tag, attrs):
            if tag not in _VOID_TAGS:
                self.skip_stack.append(tag)
            return
        if tag in {"p", "div", "article", "main", "section", "li", "h1", "h2", "h3", "h4", "br"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self.skip_stack:
            for index in range(len(self.skip_stack) - 1, -1, -1):
                if self.skip_stack[index] == tag:
                    del self.skip_stack[index:]
                    break
            return
        if tag in {"p", "div", "article", "main", "section", "li", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip_stack and data and data.strip():
            self.parts.append(data.strip())


def _strip_html(value: str) -> str:
    if not re.search(r"<\s*/?\s*[a-zA-Z][^>]*>", value):
        return value
    parser = _ReadableHTML()
    try:
        parser.feed(value)
        parser.close()
        return "\n".join(parser.parts)
    except Exception:
        # Conservative fallback: remove tags, but continue through text validation.
        return re.sub(r"<[^>]{0,500}>", " ", value)


def _clean_fragments(value: str) -> List[str]:
    # HTML entities and common layout separators can appear in provider excerpts.
    text = html.unescape(value).replace("\x00", " ").replace("\r", "\n")
    text = re.sub(r"(?i)\b(?:jump to|skip to)\s*:?\s*(?:content|main content|navigation)?", " ", text)
    text = re.sub(r"(?i)\b(?:terms\s*&\s*conditions|privacy policy)\b", " ", text)
    text = re.sub(r"(?is)explore your membership perks.*?(?:sign out|jump to:?|$)", " ", text)
    text = re.sub(r"(?is)get the\s+.{0,100}?newsletter.*?(?:aged 16 or over|$)", " ", text)
    text = re.sub(r"(?is)by submitting your information.*?(?:aged 16 or over|$)", " ", text)
    # Wikimedia navigation/disambiguation sidebars are sometimes flattened into
    # search excerpts and must not be mistaken for article prose.
    text = re.sub(r"(?is)(?:appearance\s+)?from wikipedia, the free encyclopedia.*?(?:uncertainty\.{0,3}|$)", " ", text)
    text = re.sub(r"(?i)\b(?:quantum entanglement|solar system|photosynthesis)\s+faqs?\b", " ", text)
    text = re.sub(r"(?is)have we proven quantum entanglement\?.*?additional resources", " ", text)
    text = re.sub(r"(?i)\bkey details\s*:", " ", text)
    text = re.sub(r"(?i)\b(?:appearance|key takeaway|additional resources)\b", " ", text)
    text = re.sub(r"[\t\f\v]+", " ", text)

    # Split long single-line snippets as well as ordinary paragraphs. This is
    # deliberately deterministic; it does not attempt to invent a summary.
    chunks = re.split(r"(?:\n+|(?<=[.!?])\s+|\s{2,})", text)
    cleaned: List[str] = []
    seen = set()
    for chunk in chunks:
        part = re.sub(r"\s+", " ", chunk).strip(" .,!?:;\t\n•|·-–—")
        if not part:
            continue
        low = part.casefold()
        if _BOILERPLATE.search(part):
            continue
        if re.fullmatch(r"(?i)(?:faqs?|sign in|sign out|home|menu|search|subscribe|newsletter|additional resources|related articles|contents)", part):
            continue
        # Reject fragments that are essentially navigation labels rather than prose.
        words = re.findall(r"[A-Za-z0-9]+", part)
        if len(words) <= 4 and not re.search(r"[.!?]", part):
            continue
        key = re.sub(r"[^a-z0-9]+", " ", low).strip()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(part)
    return cleaned


def clean_evidence_text(value: Any, *, max_chars: int = 12000) -> str:
    """Return clean readable source text, excluding common page chrome."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    raw = _strip_html(raw)
    fragments = _clean_fragments(raw)
    result = " ".join(fragments)
    result = re.sub(r"\s+", " ", result).strip()
    if not result or len(result) < 10:
        return ""
    return result[:max(100, int(max_chars))]


def is_useful_evidence(value: Any, *, min_chars: int = 35) -> bool:
    text = clean_evidence_text(value)
    if len(text) < min_chars:
        return False
    lowered = text.casefold()
    bad_markers = (
        "access denied", "page not found", "internal server error",
        "search timed out", "web search failed", "rate limit exceeded",
        "temporarily unavailable", "enable javascript to view this page",
    )
    if any(marker in lowered for marker in bad_markers):
        return False
    return len(re.findall(r"\w+", text)) >= 8


def hide_source_references(text: Any) -> str:
    """Hide citation blocks in user-facing channels while retaining stored evidence."""
    value = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    # Source/citation sections are appended by the deterministic answer composer.
    # Strip from the section heading onward, including same-line citation lists.
    match = re.search(r"(?im)^\s*(?:sources|references|citations)\s*:", value)
    if match:
        value = value[:match.start()].rstrip()
    # Legacy templates sometimes use a singular source line without a section.
    value = re.sub(
        r"(?im)^\s*(?:source|reference|citation|source url|url)\s*:\s*.*https?://\S+.*?$",
        "", value,
    )
    # Remove legacy citation bullets that have no explicit Sources heading.
    value = re.sub(
        r"(?im)^\s*[•*\-]\s*[^\n]{0,300}https?://\S+[^\n]*$",
        "", value,
    )
    value = re.sub(r"(?m)^\s*(?:[•*\-]\s*)?https?://\S+\s*$", "", value)
    # If an inline markdown link appears in ordinary prose, keep its label but
    # hide the destination URL from Telegram.
    value = re.sub(r"\[([^\]]+)\]\(https?://[^)]+\)", r"\1", value)
    value = re.sub(r"\n{3,}", "\n\n", value).strip()
    return value
