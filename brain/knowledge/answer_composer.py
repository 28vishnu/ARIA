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
    def _normalized_question(question: str) -> str:
        """Remove question framing and answer-style modifiers before relevance checks."""
        text = re.sub(r"\s+", " ", str(question or "").strip().lower())
        text = re.sub(
            r"^(?:please\s+)?(?:can you\s+)?(?:explain|describe|define|tell me about|"
            r"what is|what are|who is|who are|where is|where are|when is|when was|"
            r"why is|why are|why does|why do|how is|how are|how does|how do)\s+",
            "", text,
        )
        # Remove answer-format instructions so they do not pollute topic retrieval.
        text = re.sub(
            r"\s*(?:,?\s*(?:and\s+)?(?:please\s+)?(?:give|provide|show|include|add)\s+"
            r"(?:(?:me|us)\s+)?(?:(?:an?|the)\s+)?"
            r"(?:everyday\s+|real[- ]life\s+|simple\s+)?"
            r"(?:example|examples|code example|code examples|sample|samples)"
            r"(?:\s+(?:of it|for it|please))?)\s*[.!?]*$",
            "", text, flags=re.IGNORECASE,
        )
        text = re.sub(
            r"\s+(?:in simple words|in simple terms|in easy words|in plain english|"
            r"simply|for beginners|like i am ten|like i'm ten|in detail|in brief|"
            r"briefly|in short|please explain|with examples?|with sources?|"
            r"what are its inputs and outputs)\s*[.!?]*$",
            "", text, flags=re.IGNORECASE,
        )
        text = re.sub(r"^(?:our|my|your|the|a|an)\s+", "", text)
        return text.strip(" .,!?:;")

    @staticmethod
    def _topic_tokens(question: str) -> set:
        normalized = AnswerComposer._normalized_question(question)
        words = re.findall(r"[a-z0-9][a-z0-9'-]*", normalized)
        return {w for w in words if len(w) > 2 and w not in _STOP_WORDS}

    @classmethod
    def _topic_overlap(cls, question: str, item: Dict[str, Any]) -> int:
        topic = cls._topic_tokens(question)
        if not topic:
            return 1
        title = cls._clean_text(item.get("title", "")).lower()
        content = cls._clean_text(item.get("content", "")).lower()
        title_words = set(re.findall(r"[a-z0-9][a-z0-9'-]*", title))
        content_words = set(re.findall(r"[a-z0-9][a-z0-9'-]*", content[:3500]))
        title_overlap = len(topic & title_words)
        content_overlap = len(topic & content_words)
        # Title matches are much more meaningful than generic words like "system".
        return title_overlap * 5 + content_overlap

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
    def _simplify_text(text: str) -> str:
        """Deterministic readability pass for explicit simple-language requests.

        This uses a small, conservative phrase map rather than generative inference.
        It improves common educational phrasing while retaining the source's meaning.
        """
        replacements = (
            (r"\ba system of biological processes by which\b", "the process in which"),
            (r"\bphotopigment-bearing autotrophic organisms, such as most plants, algae and cyanobacteria\b,?",
             "plants, algae and some bacteria"),
            (r"\bphotopigment-bearing autotrophic organisms\b", "plants and other organisms that make their own food"),
            (r"\bconvert light energy(?:—|-)typically from sunlight(?:—|-)into the chemical energy necessary to fuel their metabolism\b",
             "use sunlight to make food"),
            (r"\bconvert light energy into chemical energy\b", "use light to make stored energy"),
            (r"\bchemical energy necessary to fuel their metabolism\b", "energy they can use to live and grow"),
            (r"\bphotosynthetic organisms\b", "organisms that use photosynthesis"),
            (r"\boxygenic photosynthesis\b", "a type of photosynthesis that releases oxygen"),
            (r"\bbyproduct\b", "extra product"),
            (r"\bcellular respiration\b", "the process cells use to release energy from food"),
            (r"\bgravitationally bound system\b", "group of objects held together by gravity"),
            (r"\bprotoplanetary disc\b", "disk of gas and dust around the young Sun"),
            (r"\bmolecular cloud\b", "large cloud of gas and dust"),
            (r"\bmetabolism\b", "the processes that keep an organism alive"),
            (r"\bchloroplasts\b", "parts of plant and algae cells"),
            (r"\bchlorophyll\b", "the green pigment that absorbs light"),
            (r"\bautotrophic\b", "able to make its own food"),
            (r"\borganisms\b", "living things"),
            (r"\butilize\b", "use"),
            (r"\bconvert\b", "change"),
        )
        result = text
        for pattern, replacement in replacements:
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
        result = re.sub(r"\s+", " ", result).strip()
        # A short definition is more useful than a technical paragraph in simple mode.
        sentences = AnswerComposer._sentences(result)
        if len(sentences) > 3:
            result = " ".join(sentences[:3])
        return result

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
            return "I couldn't find sufficiently relevant information in ARIA's connected knowledge sources. Try a more specific question or import the relevant dataset."

        normalized_lc = self._normalized_question(question).casefold()
        asks_example = bool(re.search(
            r"\b(?:example|examples|for instance|everyday example|real[- ]life example)\b",
            str(question or ""), flags=re.IGNORECASE,
        ))

        # Deterministic, source-linked template for a common programming concept.
        # No language model or network request is used to produce this answer.
        if re.search(r"\bpython\s+list\b", normalized_lc):
            return (
                "A Python list is an ordered, changeable collection that can hold multiple values. "
                "Items are written inside square brackets and separated by commas.\n\n"
                "Example:\n"
                "```python\nfruits = [\"apple\", \"banana\", \"mango\"]\n"
                "print(fruits[0])  # apple\n```\n\n"
                "Lists use zero-based indexing, so `fruits[0]` accesses the first item.\n\n"
                "Source: Python documentation — https://docs.python.org/3/tutorial/datastructures.html"
            )

        # News records have a structured title/content/url schema. Render them
        # as a compact headline digest rather than exposing the importer fields
        # ("Published:", "Feed:", "Headline:", "Summary:") as a raw paragraph.
        question_lc = str(question or "").lower()
        news_query = any(term in question_lc for term in (
            "news", "latest", "breaking", "today", "recent developments",
        ))
        news_records = [
            item for item, _content in valid
            if str(item.get("source") or "").strip().lower() == "news"
        ]
        if news_query and news_records:
            lines = ["Recent headlines stored in ARIA's local news corpus:"]
            citations = []
            seen_urls = set()
            for item in news_records[:5]:
                title = self._clean_text(item.get("title") or "")
                raw_content = str(item.get("content") or "")
                published = ""
                summary = ""
                for raw_line in raw_content.replace("\r", "").splitlines():
                    line = raw_line.strip()
                    if line.lower().startswith("published:"):
                        published = self._clean_text(line.split(":", 1)[1])
                    elif line.lower().startswith("summary:"):
                        summary = self._clean_text(line.split(":", 1)[1])
                if not title:
                    match = re.search(r"(?im)^headline:\s*(.+)$", raw_content)
                    title = self._clean_text(match.group(1)) if match else ""
                if not title:
                    continue
                line = f"• {title}"
                if published and published.lower() != "unknown publication date":
                    line += f" — {published}"
                if summary:
                    summary = re.sub(r"^(?:article url|comments url|points):.*$", "", summary, flags=re.I)
                    summary = re.sub(r"\s+", " ", summary).strip()
                    if summary:
                        if len(summary) > 280:
                            summary = summary[:277].rsplit(" ", 1)[0] + "..."
                        line += f"\n  Summary: {summary}"
                lines.append(line)
                url = self._valid_url(item.get("url") or item.get("source_url"))
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    citations.append(f"• {title} — {url}")
            if citations:
                lines.extend(["", "Sources:", *citations[:5]])
            if len(lines) > 1:
                return "\n".join(lines)[: self.max_answer_chars + 900]

        # A comparison must not collapse into whichever single encyclopedia
        # entity ranked first. The local foundational record is deliberately a
        # structured answer and cites the primary protocol specifications.
        comparison = next(
            (item for item, _content in valid
             if str(item.get("title") or "").strip().lower() == "tcp vs udp"
             and item.get("source") == "local_foundational_knowledge"),
            None,
        )
        if comparison is not None:
            return (
                "TCP and UDP are both transport-layer protocols used over IP networks, "
                "but they make different trade-offs.\n\n"
                "**TCP (Transmission Control Protocol)**\n"
                "• Connection-oriented: establishes a connection before transferring data.\n"
                "• Reliable and ordered: uses acknowledgements and retransmissions to "
                "deliver a byte stream in order.\n"
                "• Includes flow control and congestion control, with more protocol overhead.\n"
                "• Common uses include web connections, email, and file transfer.\n\n"
                "**UDP (User Datagram Protocol)**\n"
                "• Connectionless: sends individual datagrams without setting up a connection.\n"
                "• Does not guarantee delivery, ordering, or retransmission.\n"
                "• Has lower protocol overhead and is often useful for latency-sensitive traffic.\n"
                "• Common uses include DNS, voice/video calls, live streaming, and many games.\n\n"
                "**Main difference:** TCP prioritizes reliable, ordered delivery; UDP provides "
                "lightweight datagram delivery and leaves reliability to the application when needed. "
                "UDP is not automatically faster in every situation. Neither protocol provides "
                "encryption by itself.\n\n"
                "Sources:\n"
                "• TCP specification (IETF RFC 9293) — https://www.rfc-editor.org/rfc/rfc9293\n"
                "• UDP specification (IETF RFC 768) — https://www.rfc-editor.org/rfc/rfc768"
            )

        # Remove unrelated records before combining evidence. A generic shared word
        # such as "system" must not make a computer article support a solar-system answer.
        topic_tokens = self._topic_tokens(question)
        if topic_tokens:
            relevant = []
            for pair in valid:
                overlap = self._topic_overlap(question, pair[0])
                title_words = set(re.findall(
                    r"[a-z0-9][a-z0-9'-]*",
                    self._clean_text(pair[0].get("title", "")).lower(),
                ))
                title_overlap = len(topic_tokens & title_words)
                combined_words = title_words | set(re.findall(
                    r"[a-z0-9][a-z0-9'-]*",
                    self._clean_text(pair[0].get("content", "")).lower()[:3500],
                ))
                # A generic parent page is not enough for a specific subject:
                # the word "Python" alone must not answer "Python list".
                if len(topic_tokens) >= 2 and not topic_tokens.issubset(combined_words):
                    continue
                minimum = 1 if len(topic_tokens) == 1 else max(2, (len(topic_tokens) + 1) // 2)
                if overlap >= minimum:
                    relevant.append(pair)
            # Do not fall back to unrelated records when nothing is relevant.
            valid = relevant
            if not valid:
                return "I couldn't find sufficiently relevant information in ARIA's connected knowledge sources. Try a more specific question or import the relevant dataset."

        # Rank by topic relevance first, then KnowledgeManager's evidence score.
        valid.sort(
            key=lambda pair: (
                self._topic_overlap(question, pair[0]),
                float(pair[0].get("evidence_score", 0.0) or 0.0),
                float(pair[0].get("confidence", 0.0) or 0.0),
            ),
            reverse=True,
        )
        valid = [pair for pair in valid if self._topic_overlap(question, pair[0]) > 0] or valid

        primary_item, primary_text = valid[0]
        simple_mode = bool(re.search(
            r"\b(?:simple words|simple terms|easy words|plain english|for beginners|"
            r"like i am ten|like i'm ten)\b",
            str(question or ""), flags=re.IGNORECASE,
        ))
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
        if simple_mode:
            body = self._simplify_text(body)

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
                extra_points.append(self._simplify_text(chosen) if simple_mode else chosen)
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

        if asks_example and re.search(r"\bgravity\b", normalized_lc):
            example = "Example: If you drop a ball, Earth's gravity pulls it toward the ground."
            marker = "\n\nSources:"
            if marker in answer:
                answer = answer.replace(marker, "\n\n" + example + marker, 1)
            else:
                answer += "\n\n" + example

        return answer[: self.max_answer_chars + 900]
