"""Deterministic answer composition for ARIA's unified knowledge brain.

This module formats retrieved evidence using ordinary Python only. It never
calls an LLM, remote service, or external text-generation endpoint.
"""
from __future__ import annotations

import html
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit


_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "between", "by",
    "can", "could", "did", "do", "does", "for", "from", "give",
    "how", "i", "in", "into", "is", "it", "its", "me", "of", "on",
    "or", "please", "provide", "tell", "that", "the", "their", "this",
    "to", "use", "was", "what", "when", "where", "which", "who", "why",
    "with", "would", "you", "your", "explain", "describe", "define",
    "about", "source", "url", "only", "local", "stored", "knowledge",
    "database", "aria", "answer", "using", "without", "external", "model",
}

_FAILURE_MARKERS = (
    "temporarily unable to reach my language models",
    "unable to reach my language models",
    "all available llm providers failed",
    "all available llm provider failed",
    "please try again in a few seconds",
    "language model is unavailable",
    "language models are unavailable",
    "service unavailable",
)


class AnswerComposer:
    """Turn one or more retrieved records into a readable, cited answer."""

    def __init__(self, max_answer_chars: int = 1500, max_sources: int = 4):
        self.max_answer_chars = max(300, int(max_answer_chars))
        self.max_sources = max(1, min(int(max_sources), 8))

    @staticmethod
    def _clean_text(value: Any) -> str:
        text = html.unescape(str(value or ""))
        text = text.replace("\x00", " ").replace("\r", "\n")
        text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.I | re.S)
        text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\[\[(?:File|Image):[^\]]+\]\]", " ", text, flags=re.I)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    @staticmethod
    def _valid_url(value: Any) -> str:
        url = str(value or "").strip().strip("<>\"' ")
        url = url.rstrip(".,;:!?\"'")
        if not url:
            return ""
        try:
            parsed = urlsplit(url)
        except ValueError:
            return ""
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return ""
        return url

    @classmethod
    def _is_failure_or_wrapper(cls, text: str) -> bool:
        lowered = text.lower().strip()
        if not lowered or any(marker in lowered for marker in _FAILURE_MARKERS):
            return True
        # Reject the previously observed conversation-wrapper pollution.
        if lowered.startswith("query:") and "answer:" in lowered:
            return True
        if lowered.startswith("what is photosynthesis") and "temporarily unable" in lowered:
            return True
        return False

    @staticmethod
    def _sentences(text: str) -> List[str]:
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return []
        parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(\"'])", text)
        return [part.strip() for part in parts if part.strip()]

    @staticmethod
    def _topic_tokens(question: str) -> set:
        words = re.findall(r"[a-z0-9][a-z0-9'-]*", question.lower())
        return {w for w in words if len(w) > 2 and w not in _STOP_WORDS}

    @classmethod
    def _topic_overlap(cls, question: str, item: Dict[str, Any]) -> int:
        topic = cls._topic_tokens(question)
        if not topic:
            return 1
        title = cls._clean_text(item.get("title", "")).lower()
        content = cls._clean_text(item.get("content", "")).lower()
        title_words = set(re.findall(r"[a-z0-9][a-z0-9'-]*", title))
        content_words = set(re.findall(r"[a-z0-9][a-z0-9'-]*", content[:2500]))
        return len(topic & title_words) * 3 + len(topic & content_words)

    @classmethod
    def _readable_evidence(cls, item: Dict[str, Any]) -> str:
        content = cls._clean_text(item.get("content", ""))
        if not content or cls._is_failure_or_wrapper(content):
            return ""
        # Avoid dumping JSON objects, Mongo documents, or Wikidata claim blobs.
        if content[:1] in "{[" and any(token in content[:120].lower() for token in ('"claims"', '"entities"', '"_id"', '"content"')):
            return ""
        return content

    @staticmethod
    def _source_label(item: Dict[str, Any]) -> str:
        source = str(item.get("source") or "knowledge base").strip().replace("_", " ")
        title = AnswerComposer._clean_text(item.get("title", ""))
        if title and len(title) <= 120:
            return f"{title} ({source})"
        return source[:80] or "knowledge base"

    def compose(self, question: str, evidence: Sequence[Dict[str, Any]]) -> str:
        valid: List[Tuple[Dict[str, Any], str]] = []
        seen_content = set()
        for raw in evidence or []:
            if not isinstance(raw, dict):
                continue
            content = self._readable_evidence(raw)
            if not content:
                continue
            key = re.sub(r"\W+", " ", content.lower()).strip()
            if key in seen_content:
                continue
            seen_content.add(key)
            valid.append((raw, content))

        if not valid:
            return "I couldn't find reliable information in ARIA's connected knowledge sources."

        # Rank by KnowledgeManager's evidence score, then topic overlap.
        valid.sort(
            key=lambda pair: (
                float(pair[0].get("evidence_score", 0.0) or 0.0),
                self._topic_overlap(question, pair[0]),
                float(pair[0].get("confidence", 0.0) or 0.0),
            ),
            reverse=True,
        )
        valid = [pair for pair in valid if self._topic_overlap(question, pair[0]) > 0] or valid

        primary_item, primary_text = valid[0]
        title = self._clean_text(primary_item.get("title", ""))
        # Do not use a title that is just the entire question or an internal key.
        q_clean = re.sub(r"[^a-z0-9]+", " ", question.lower()).strip()
        title_clean = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
        heading = title if title_clean and title_clean != q_clean and len(title) <= 90 else ""

        sentences = self._sentences(primary_text)
        if not sentences:
            sentences = [primary_text]

        # Keep a useful, bounded extract rather than dumping the full article.
        lead_parts: List[str] = []
        current_len = 0
        sentence_limit = 4 if len(primary_text) > 500 else 6
        for sentence in sentences[:sentence_limit]:
            if len(sentence) > 600:
                sentence = sentence[:597].rsplit(" ", 1)[0] + "..."
            if current_len + len(sentence) > self.max_answer_chars:
                remaining = self.max_answer_chars - current_len
                if remaining > 100:
                    lead_parts.append(sentence[:remaining - 3].rsplit(" ", 1)[0] + "...")
                break
            lead_parts.append(sentence)
            current_len += len(sentence) + 1
        body = " ".join(lead_parts).strip()

        # Bring in corroborating facts from other systems only when they match
        # the same topic and add distinct information. No paraphrasing model.
        extra_points: List[str] = []
        source_records: List[Dict[str, Any]] = [primary_item]
        primary_sentences = {re.sub(r"\W+", " ", s.lower()).strip() for s in sentences}
        for item, content in valid[1:]:
            if len(source_records) >= self.max_sources:
                break
            if self._topic_overlap(question, item) <= 0:
                continue
            candidate_sentences = self._sentences(content)
            chosen = None
            for sentence in candidate_sentences[:5]:
                norm = re.sub(r"\W+", " ", sentence.lower()).strip()
                if len(sentence) < 35 or norm in primary_sentences:
                    continue
                if len(sentence) > 240:
                    sentence = sentence[:237].rsplit(" ", 1)[0] + "..."
                chosen = sentence
                break
            if chosen:
                extra_points.append(chosen)
                source_records.append(item)

        pieces: List[str] = []
        if heading:
            pieces.append(heading)
        pieces.append(body or primary_text[:self.max_answer_chars])
        if extra_points:
            pieces.append("Key details:\n" + "\n".join(f"• {point}" for point in extra_points[:3]))

        citations: List[str] = []
        seen_urls = set()
        for item in source_records:
            metadata = item.get("metadata")
            url_value = item.get("url") or item.get("source_url")
            if not url_value and isinstance(metadata, dict):
                url_value = metadata.get("url")
            url = self._valid_url(url_value)
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            citations.append(f"• {self._source_label(item)} — {url}")

        if citations:
            pieces.append("Sources:\n" + "\n".join(citations))

        answer = "\n\n".join(piece for piece in pieces if piece).strip()
        return answer[: self.max_answer_chars + 900]
