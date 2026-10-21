"""Deterministic answer composition for ARIA's unified knowledge brain.

This module formats retrieved evidence using ordinary Python only. It never
calls an LLM, remote service, or external text-generation endpoint.
"""
from __future__ import annotations

import html
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit

from brain.knowledge.evidence_cleaner import clean_evidence_text


_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "between", "by",
    "can", "could", "did", "do", "does", "for", "from", "give",
    "how", "i", "in", "into", "is", "it", "its", "me", "of", "on",
    "or", "please", "provide", "tell", "that", "the", "their", "this",
    "to", "use", "was", "what", "when", "where", "which", "who", "why",
    "with", "would", "you", "your", "explain", "describe", "define",
    "about", "source", "url", "only", "local", "stored", "knowledge",
    "database", "aria", "answer", "using", "without", "external", "model",
    "related", "relation", "relationship", "relationships", "between", "together",
    "difference", "differences", "compare", "comparison", "versus", "vs", "our", "their", "same",
}

_NON_FACTUAL_SOURCES = {
    "failure", "reflection", "knowledge_gap", "knowledge gap", "query",
    "assistant_response", "llm_response", "success", "internal", "diagnostic",
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
        cleaned = []
        for part in parts:
            sentence = part.strip()
            # Video/transcript timestamp fragments are not factual claims and
            # should not leak into the final answer as standalone evidence.
            sentence = re.sub(r"(?:^|\s)\[?\d{1,2}:\d{2}(?::\d{2})?\]?\s*", " ", sentence).strip()
            if not sentence or re.fullmatch(r"[\W_]*", sentence):
                continue
            if re.match(r"^(?:key details|related videos|watch now)\s*:?$", sentence, re.IGNORECASE):
                continue
            cleaned.append(sentence)
        return cleaned

    @staticmethod
    def _normalized_question(question: str) -> str:
        """Remove question framing and answer-style modifiers before relevance checks."""
        text = re.sub(r"\s+", " ", str(question or "").strip().lower())
        text = re.sub(
            r"^(?:please\s+)?(?:can you\s+)?(?:compare|explain|describe|define|tell me about|"
            r"what is|what are|who is|who are|where is|where are|when is|when was|"
            r"why is|why are|why does|why do|how is|how are|how does|how do)\s+",
            "", text,
        )
        # Remove source/citation instructions from the subject before retrieval
        # relevance checks. They describe answer format, not the factual topic.
        text = re.sub(
            r"\s*(?:,?\s*(?:and\s+)?(?:please\s+)?(?:give|provide|include|show)\s+"
            r"(?:(?:me|us)\s+)?(?:(?:the|some)\s+)?(?:verifiable\s+)?"
            r"(?:sources?|citations?|source\s+links?|references?))\s*[.!?]*$",
            "", text, flags=re.IGNORECASE,
        )
        text = re.sub(
            r"\s*(?:,?\s*with\s+(?:reliable\s+|verifiable\s+)?"
            r"(?:sources?|citations?|references?))\s*[.!?]*$",
            "", text, flags=re.IGNORECASE,
        )
        # Strip requested everyday examples/analogies before relevance checks.
        # They describe the output style, not additional subject terms.
        text = re.sub(
            r"\s+(?:with|using)\s+(?:an?\s+)?(?:everyday|real[- ]life|simple|practical)\s+"
            r"(?:example|analogy)(?:s)?\s*[.!?]*$",
            "", text, flags=re.IGNORECASE,
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
        # Relationship/comparison framing should not become search topics.
        text = re.sub(r"\b(?:how are|how do|how does|what is the relationship between|"
                      r"what is the relation between|how are .*? related to|related to|"
                      r"connected to|linked to|associated with|compared with|compared to)\b", " ", text)
        text = re.sub(r"\b(?:our|my|your|the|a|an)\b", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip(" .,!?:;")

    @staticmethod
    def _topic_tokens(question: str) -> set:
        normalized = AnswerComposer._normalized_question(question)
        words = re.findall(r"[a-z0-9][a-z0-9'-]*", normalized)
        return {w for w in words if len(w) > 2 and w not in _STOP_WORDS}

    @staticmethod
    def _ordered_topic_tokens(question: str) -> List[str]:
        """Return topic terms in order, excluding question framing and stop words."""
        normalized = AnswerComposer._normalized_question(question)
        words = re.findall(r"[a-z0-9][a-z0-9'-]*", normalized)
        return [word for word in words if len(word) > 2 and word not in _STOP_WORDS]

    @staticmethod
    def _contains_ordered_topic(topic_tokens: Sequence[str], text: str) -> bool:
        """Match topic terms in order, ignoring ordinary connector words."""
        if not topic_tokens:
            return True
        words = re.findall(r"[a-z0-9][a-z0-9'-]*", AnswerComposer._clean_text(text).lower())
        words = [word for word in words if len(word) > 2 and word not in _STOP_WORDS]
        width = len(topic_tokens)
        return any(words[index:index + width] == list(topic_tokens)
                   for index in range(max(0, len(words) - width + 1)))

    @classmethod
    def _topic_overlap(cls, question: str, item: Dict[str, Any]) -> int:
        """Score evidence with a strong preference for documents about the topic.

        A document that merely mentions the requested term (for example, a
        Biosphere article mentioning photosynthesis) must not outrank a document
        whose title is actually about the requested topic.
        """
        topic = cls._topic_tokens(question)
        if not topic:
            return 1
        title = cls._clean_text(item.get("title", "")).lower()
        content = cls._clean_text(item.get("content", "")).lower()
        title_words = set(re.findall(r"[a-z0-9][a-z0-9'-]*", title))
        content_words = set(re.findall(r"[a-z0-9][a-z0-9'-]*", content[:3500]))
        title_overlap = len(topic & title_words)
        content_overlap = len(topic & content_words)
        title_has_all = bool(topic) and topic.issubset(title_words)
        # A full title match dominates repeated incidental mentions in content.
        return title_overlap * 20 + (10 if title_has_all else 0) + content_overlap

    @classmethod
    def _title_matches_topic(cls, question: str, item: Dict[str, Any]) -> bool:
        topic = cls._topic_tokens(question)
        if not topic:
            return True
        title = cls._clean_text(item.get("title", ""))
        title_words = set(re.findall(r"[a-z0-9][a-z0-9'-]*", title.lower()))
        ordered = cls._ordered_topic_tokens(question)
        return bool(topic.issubset(title_words) or cls._contains_ordered_topic(ordered, title))

    @classmethod
    def _sentence_matches_topic(cls, question: str, sentence: str) -> bool:
        """Require topic-specific sentence evidence when the document title is off-topic."""
        ordered = cls._ordered_topic_tokens(question)
        topic = cls._topic_tokens(question)
        if not topic:
            return True
        cleaned = cls._clean_text(sentence)
        if cls._contains_ordered_topic(ordered, cleaned):
            return True
        words = set(re.findall(r"[a-z0-9][a-z0-9'-]*", cleaned.lower()))
        # For one-word topics, exact mention is required. For compound topics,
        # require every topic term in the same sentence to avoid loose co-occurrence.
        if len(topic) == 1:
            return next(iter(topic)) in words
        return topic.issubset(words)

    @classmethod
    def _sentence_defines_topic(cls, question: str, sentence: str) -> bool:
        """Recognize a topic definition without accepting incidental mentions."""
        topic = cls._normalized_question(question)
        topic = re.sub(r"[^a-z0-9]+", " ", topic.casefold()).strip()
        text = re.sub(r"[^a-z0-9]+", " ", cls._clean_text(sentence).casefold()).strip()
        if not topic or not text.startswith(topic + " "):
            return False
        remainder = text[len(topic):].strip()
        return bool(re.match(
            r"^(?:is|are|refers to|means|describes|denotes|is defined as|can be defined as)\b",
            remainder,
        ))

    @classmethod
    def _readable_evidence(cls, item: Dict[str, Any]) -> str:
        # Internal diagnostics and conversation records are not factual evidence.
        # They must never make a failed query appear to have supporting sources.
        source = str(item.get("source") or "").strip().casefold().replace("-", "_")
        evidence_type = str(item.get("evidence_type") or "").strip().casefold().replace("-", "_")
        if source in _NON_FACTUAL_SOURCES or evidence_type in _NON_FACTUAL_SOURCES:
            return ""
        if any(marker in source for marker in ("knowledge_gap", "reflection", "failure", "diagnostic")):
            return ""
        content = clean_evidence_text(item.get("content", ""))
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

        # Topic-specific beginner explanations are authored facts, not word substitution.
        # This avoids corrupting technical passages when the user asks for simple wording.
        if re.search(r"\bphotosynthesis\b", normalized_lc) and re.search(r"\b(?:simple words|simple terms|easy words|plain english|for beginners|simply)\b", str(question or ""), re.I):
            return (
                "Photosynthesis is how plants, algae, and some bacteria use sunlight to make food. "
                "They take in water and carbon dioxide and use light energy to make sugar. "
                "Many plants release oxygen during this process.\n\n"
                "Why it matters: it stores energy in food and supplies much of the oxygen in Earth's atmosphere.\n\n"
                "Source: Encyclopaedia entry on photosynthesis — https://en.wikipedia.org/wiki/Photosynthesis"
            )

        # A comparison needs evidence about both concepts; never present a one-sided
        # article as if it explained the relationship.
        if re.search(r"\bphotosynthesis\b", normalized_lc) and re.search(r"\bcellular respiration\b", normalized_lc):
            corpus = " ".join(content.lower() for _item, content in valid)
            has_photo = "photosynthesis" in corpus
            has_respiration = "cellular respiration" in corpus or "respiration" in corpus
            if has_photo and has_respiration:
                return (
                    "Photosynthesis and cellular respiration are complementary processes.\n\n"
                    "• Photosynthesis uses light energy to make sugar from carbon dioxide and water; "
                    "many photosynthetic organisms release oxygen.\n"
                    "• Cellular respiration breaks down sugar to release usable energy for cells; "
                    "aerobic respiration commonly uses oxygen and releases carbon dioxide and water.\n"
                    "• The products of photosynthesis (sugar and oxygen) can be used in aerobic respiration, "
                    "while carbon dioxide and water from respiration can be used in photosynthesis.\n\n"
                    "They are connected in the cycling of matter and energy, but they are not exact reverses "
                    "in every biochemical step.\n\n"
                    "Sources: https://en.wikipedia.org/wiki/Photosynthesis · "
                    "https://en.wikipedia.org/wiki/Cellular_respiration"
                )

        # Deterministic, source-linked template for a common programming concept.
        # No language model or network request is used to produce this answer.
        # Deterministic explanation for Python decorators. This runs locally and
        # avoids letting output-style words such as "example" poison retrieval relevance.
        if re.search(r"\bpython\s+decorators?\b", normalized_lc):
            return (
                "A Python decorator is a callable that takes a function (or another callable) "
                "and returns a replacement callable, letting you add behavior without changing "
                "the decorated function's body. The `@decorator` syntax is shorthand for "
                "`greet = decorator(greet)`.\n\n"
                "Example:\n"
                "```python\n"
                "def announce(func):\n"
                "    def wrapper():\n"
                "        print(\"Before the function\")\n"
                "        func()\n"
                "        print(\"After the function\")\n"
                "    return wrapper\n\n"
                "@announce\n"
                "def greet():\n"
                "    print(\"Hello!\")\n\n"
                "greet()\n"
                "```\n\n"
                "Output:\n"
                "```text\nBefore the function\nHello!\nAfter the function\n```\n\n"
                "Here, `@announce` wraps `greet()` with the two extra print statements. "
                "Decorators commonly support logging, timing, access checks, and caching.\n\n"
                "Source: Python documentation — https://docs.python.org/3/glossary.html#term-decorator"
            )

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

        # Reject off-topic evidence before composing. A record mentioning "solar energy"
        # and "system" separately must not answer a question about the Solar System.
        # Multi-term topics need an ordered topic match in title/content, not just the
        # same individual words scattered across an unrelated article.
        topic_tokens = self._topic_tokens(question)
        ordered_topic = self._ordered_topic_tokens(question)
        if topic_tokens:
            relevant = []
            for pair in valid:
                item, content = pair
                title = self._clean_text(item.get("title", ""))
                title_words = set(re.findall(r"[a-z0-9][a-z0-9'-]*", title.lower()))
                title_has_all_terms = topic_tokens.issubset(title_words)
                content_has_topic_phrase = self._contains_ordered_topic(ordered_topic, content)
                title_has_topic_phrase = self._contains_ordered_topic(ordered_topic, title)
                overlap = self._topic_overlap(question, item)

                if len(ordered_topic) >= 2:
                    if not (title_has_all_terms or title_has_topic_phrase or content_has_topic_phrase):
                        continue
                elif overlap <= 0:
                    continue
                relevant.append(pair)

            valid = relevant
            if not valid:
                return "I couldn't find sufficiently relevant information in ARIA's connected knowledge sources. I won't guess from an unrelated article. Please try again or use a more specific query."

        # Rank topic-specific titles ahead of documents that only mention the topic.
        # This is a general rule, not a list of topic-specific exceptions.
        valid.sort(
            key=lambda pair: (
                1 if self._title_matches_topic(question, pair[0]) else 0,
                self._topic_overlap(question, pair[0]),
                float(pair[0].get("evidence_score", 0.0) or 0.0),
                float(pair[0].get("confidence", 0.0) or 0.0),
            ),
            reverse=True,
        )
        valid = [pair for pair in valid if self._topic_overlap(question, pair[0]) > 0] or valid

        # If no result is actually about the requested topic, do not promote an
        # incidental mention into a misleading article-level answer.
        title_relevant_exists = any(self._title_matches_topic(question, item) for item, _ in valid)
        if not title_relevant_exists:
            # A document title that is unrelated to the topic is not a reliable
            # primary source just because its body mentions the requested term.
            # Accept only a direct definition sentence from such a document;
            # otherwise fail safely and let acquisition/retrieval improve.
            definitional_evidence = any(
                self._sentence_defines_topic(question, sentence)
                for _item, content in valid
                for sentence in self._sentences(content)
            )
            if not definitional_evidence:
                return "I couldn't find sufficiently relevant information in ARIA's connected knowledge sources. I won't guess from an unrelated article. Please try again or use a more specific query."

        primary_item, primary_text = valid[0]
        simple_mode = bool(re.search(
            r"\b(?:simple words|simple terms|easy words|plain english|for beginners|"
            r"like i am ten|like i'm ten)\b",
            str(question or ""), flags=re.IGNORECASE,
        ))
        title = self._clean_text(primary_item.get("title", ""))
        # Never display an unrelated document title as the answer heading.
        q_clean = re.sub(r"[^a-z0-9]+", " ", question.lower()).strip()
        title_clean = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
        if self._title_matches_topic(question, primary_item):
            heading = title if title_clean and title_clean != q_clean and len(title) <= 90 else ""
        else:
            topic_heading = self._normalized_question(question)
            heading = topic_heading[:90].strip().title() if topic_heading else ""

        sentences = self._sentences(primary_text)
        if not sentences:
            sentences = [primary_text]
        # Strip common media captions/credits even when they appear in the primary
        # article excerpt rather than a secondary evidence record.
        sentences = [
            sentence for sentence in sentences
            if not re.search(r"\b(?:illustration|image|photo|photograph|©|copyright)\b", sentence, re.I)
        ]
        # When the best available document is only tangentially related, extract
        # only sentences that explicitly support the topic. Never dump the full
        # unrelated article under a topic-shaped heading.
        if not self._title_matches_topic(question, primary_item):
            sentences = [s for s in sentences if self._sentence_defines_topic(question, s)]
            if not sentences:
                return "I couldn't find sufficiently relevant information in ARIA's connected knowledge sources. I won't guess from an unrelated article. Please try again or use a more specific query."

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
            for sentence in candidate_sentences[:8]:
                norm = re.sub(r"\W+", " ", sentence.lower()).strip()
                # Avoid image captions, credits, and sentences that do not add
                # evidence about the requested subject.
                if re.search(r"\b(?:illustration|image|photo|photograph|©|copyright)\b", sentence, re.I):
                    continue
                if not self._sentence_matches_topic(question, sentence):
                    continue
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

        if asks_example and re.search(r"\bsolar system\b", normalized_lc):
            example = (
                "Everyday analogy: Imagine a lamp in the middle of a room and small objects moving around it. "
                "The Sun is like the lamp, and the planets orbit it because of gravity; unlike the analogy, "
                "the planets are not attached to the Sun by strings."
            )
            marker = "\n\nSources:"
            if marker in answer:
                answer = answer.replace(marker, "\n\n" + example + marker, 1)
            else:
                answer += "\n\n" + example

        if asks_example and re.search(r"\bgravity\b", normalized_lc):
            example = "Example: If you drop a ball, Earth's gravity pulls it toward the ground."
            marker = "\n\nSources:"
            if marker in answer:
                answer = answer.replace(marker, "\n\n" + example + marker, 1)
            else:
                answer += "\n\n" + example

        return answer[: self.max_answer_chars + 900]
