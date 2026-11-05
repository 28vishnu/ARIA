"""Response verification and uncertainty metadata for JARVIS.

This module never invents facts, citations, or tool outputs. It only:

* extracts source links that were actually returned by retrieval tools;
* reports whether a research response has usable evidence;
* appends a source list built exclusively from retrieved evidence;
* flags links in the answer that were not found in the retrieved evidence;
* attaches explicit uncertainty metadata for the caller.

Deterministic/local answers are left untouched. The verifier is deliberately
conservative: when in doubt it reports uncertainty instead of asserting that a
claim is verified.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse

_URL_RE = re.compile(r"https?://[^\s<>\]\)\"']+", re.IGNORECASE)

# Answer sources that are already deterministic or explicitly qualified and
# must not be rewritten by the verifier.
_SKIP_SOURCES = {
    "memory_profile",
    "memory_conversation",
    "memory",
    "capability",
    "goal_manager",
    "local_knowledge",
    "local_foundational_knowledge",
    "knowledge_database",
    "knowledge_manager",
    "knowledge",
    "local_knowledge_miss",
    "llm_unavailable",
    "request_timeout",
    "safety",
    "safety_block",
}

# Sources whose claims should be supported by retrieved evidence.
_RETRIEVAL_SOURCES = {
    "research",
    "research_agent",
    "web_search",
    "web",
    "web_fallback",
    "search",
    "search_tool",
    "tavily",
    "searxng",
    "wikipedia",
    "tool",
    "external",
}

_TIME_SENSITIVE_MARKERS = (
    "today",
    "tonight",
    "tomorrow",
    "yesterday",
    "latest",
    "current",
    "currently",
    "right now",
    "this week",
    "this month",
    "this year",
    "recent",
    "recently",
    "news",
    "breaking",
    "stock price",
    "exchange rate",
    "weather",
    "forecast",
    "air quality",
    "election",
    "outage",
    "release date",
    "price of",
)

_EVIDENCE_CONTAINER_KEYS = {
    "web_results",
    "search_results",
    "sources",
    "citations",
    "evidence",
    "tool_results",
    "agent_outputs",
    "agent_coordination",
    "phase1_agent_result",
    "results",
    "result",
    "output",
    "data",
}


class ResponseVerifier:
    """Build truthful verification metadata for a generated answer."""

    VERSION = "1.0.0"
    MAX_EVIDENCE = 8
    MAX_WALK_NODES = 300

    def verify(
        self,
        answer: Any,
        source: Any = "",
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        context = context if isinstance(context, dict) else {}
        text = str(answer or "").strip()
        source_name = str(source or "").strip()

        if not text:
            return {
                "answer": text,
                "verified": False,
                "uncertainty": 1.0,
                "confidence": 0.0,
                "evidence_count": 0,
                "citations": [],
                "warnings": ["The response was empty."],
                "source": source_name,
                "verifier_version": self.VERSION,
            }

        if source_name in _SKIP_SOURCES:
            return {
                "answer": text,
                "verified": True,
                "uncertainty": 0.0,
                "confidence": None,
                "evidence_count": 0,
                "citations": [],
                "warnings": [],
                "source": source_name,
                "verifier_version": self.VERSION,
            }

        evidence = self.collect_evidence(context)
        warnings: List[str] = []

        answer_urls = self._extract_urls(text)
        evidence_urls = {item["url"] for item in evidence}
        unsupported = [
            url for url in answer_urls
            if not self._url_is_supported(url, evidence_urls)
        ]

        if unsupported and evidence:
            warnings.append(
                "Some links in the answer were not found in the retrieved "
                "evidence and remain unverified."
            )

        retrieval_expected = (
            source_name in _RETRIEVAL_SOURCES
            or bool(evidence)
        )

        time_sensitive = self._is_time_sensitive(
            str(
                context.get("original_user_query")
                or context.get("original_query")
                or context.get("query")
                or ""
            )
        )

        if retrieval_expected and not evidence and time_sensitive:
            warnings.append(
                "No live sources were available for this time-sensitive "
                "request, so current facts could not be verified."
            )
            text = self._append_once(
                text,
                "\n\nNote: I could not verify this against live sources. "
                "Treat any time-sensitive details as unconfirmed.",
                marker="could not verify this against live sources",
            )

        if evidence:
            text = self._append_sources(text, evidence)

        uncertainty = self._uncertainty(
            source_name=source_name,
            evidence_count=len(evidence),
            unsupported_count=len(unsupported),
            retrieval_expected=retrieval_expected,
        )

        verified = bool(evidence) if retrieval_expected else True
        if retrieval_expected and not evidence:
            verified = False

        return {
            "answer": text,
            "verified": verified,
            "uncertainty": round(uncertainty, 3),
            "confidence": round(max(0.0, 1.0 - uncertainty), 3),
            "evidence_count": len(evidence),
            "citations": evidence,
            "unsupported_link_count": len(unsupported),
            "warnings": warnings,
            "source": source_name,
            "retrieval_expected": retrieval_expected,
            "time_sensitive": time_sensitive,
            "verifier_version": self.VERSION,
        }

    # ------------------------------------------------------------------
    # Evidence extraction
    # ------------------------------------------------------------------

    def collect_evidence(
        self,
        context: Optional[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Return normalized evidence items that actually exist in context."""

        if not isinstance(context, dict):
            return []

        found: List[Dict[str, Any]] = []
        seen: set[str] = set()
        visited = {"count": 0}

        def add(item: Dict[str, Any]) -> None:
            url = str(item.get("url") or item.get("link") or item.get("href") or "").strip()
            title = str(item.get("title") or item.get("name") or "").strip()
            snippet = str(
                item.get("snippet")
                or item.get("content")
                or item.get("description")
                or ""
            ).strip()
            if not url and not title:
                return
            if url:
                parsed = urlparse(url)
                if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                    return
            key = url.casefold() if url else title.casefold()
            if key in seen:
                return
            seen.add(key)
            published = (
                item.get("published_date")
                or item.get("publishedDate")
                or item.get("published_at")
                or item.get("date")
            )
            found.append({
                "title": title or url,
                "url": url,
                "snippet": snippet[:400],
                "published_date": str(published)[:100] if published else None,
            })

        def walk(node: Any, depth: int = 0) -> None:
            if depth > 4 or len(found) >= self.MAX_EVIDENCE:
                return
            visited["count"] += 1
            if visited["count"] > self.MAX_WALK_NODES:
                return

            if isinstance(node, dict):
                if any(key in node for key in ("url", "link", "href")):
                    add(node)
                for key, value in node.items():
                    key_text = str(key).casefold()
                    if key_text in _EVIDENCE_CONTAINER_KEYS or depth == 0:
                        walk(value, depth + 1)
                return

            if isinstance(node, (list, tuple)):
                for item in node[: self.MAX_EVIDENCE * 3]:
                    walk(item, depth + 1)

        for key in (
            "web_results",
            "search_results",
            "sources",
            "citations",
            "tool_results",
            "agent_outputs",
            "agent_coordination",
            "phase1_agent_result",
        ):
            if key in context:
                walk(context.get(key), 1)

        return found[: self.MAX_EVIDENCE]

    @staticmethod
    def _extract_urls(text: str) -> List[str]:
        return [match.rstrip(".,;:!?") for match in _URL_RE.findall(text)]

    @staticmethod
    def _url_is_supported(url: str, evidence_urls: Iterable[str]) -> bool:
        target = url.rstrip("/").casefold()
        for candidate in evidence_urls:
            candidate_value = str(candidate).rstrip("/").casefold()
            if not candidate_value:
                continue
            if target == candidate_value:
                return True
            # Allow anchors/query-string variations on the same evidence URL.
            if target.split("?")[0].split("#")[0] == candidate_value.split("?")[0].split("#")[0]:
                return True
        return False

    # ------------------------------------------------------------------
    # Formatting
    # ------------------------------------------------------------------

    def _append_sources(
        self,
        text: str,
        evidence: List[Dict[str, Any]],
    ) -> str:
        if "sources (retrieved)" in text.casefold():
            return text

        lines = ["", "Sources (retrieved):"]
        for index, item in enumerate(evidence, start=1):
            title = item.get("title") or item.get("url") or "Untitled source"
            url = item.get("url")
            published = item.get("published_date")
            line = f"{index}. {title}"
            if url:
                line += f" - {url}"
            if published:
                line += f" (published: {published})"
            lines.append(line)

        block = "\n".join(lines)
        if all(
            (item.get("url") and item["url"] in text)
            for item in evidence
        ):
            return text
        return text.rstrip() + block

    @staticmethod
    def _append_once(text: str, addition: str, marker: str) -> str:
        if marker.casefold() in text.casefold():
            return text
        return text.rstrip() + addition

    @staticmethod
    def _is_time_sensitive(query: str) -> bool:
        value = str(query or "").casefold()
        return any(marker in value for marker in _TIME_SENSITIVE_MARKERS)

    @staticmethod
    def _uncertainty(
        source_name: str,
        evidence_count: int,
        unsupported_count: int,
        retrieval_expected: bool,
    ) -> float:
        if source_name in _SKIP_SOURCES:
            return 0.0

        if not retrieval_expected:
            base = 0.45
        elif evidence_count <= 0:
            base = 0.9
        elif evidence_count == 1:
            base = 0.45
        elif evidence_count == 2:
            base = 0.32
        else:
            base = 0.22

        if unsupported_count:
            base = min(1.0, base + 0.1 * min(unsupported_count, 3))

        return max(0.0, min(base, 1.0))
