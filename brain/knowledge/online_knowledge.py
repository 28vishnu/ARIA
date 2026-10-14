"""Deterministic on-demand knowledge acquisition; no LLM or AI-answer API."""
from __future__ import annotations

import hashlib
import logging
import os
import re
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

from brain.knowledge.evidence_cleaner import clean_evidence_text, is_useful_evidence

LOG = logging.getLogger("aria.online_knowledge")


def topic_from_question(question: str) -> str:
    """Remove question framing and answer directives without corrupting the topic."""
    topic = re.sub(r"\s+", " ", str(question or "").strip()).replace("’", "'")
    if not topic:
        return ""

    # Remove instruction phrases first so they do not become search keywords.
    directive_patterns = (
        r"\s*(?:,?\s*(?:and\s+)?(?:please\s+)?(?:provide|give|show|include)\s+(?:me\s+)?(?:the\s+)?source\s+urls?)\b.*$",
        r"\s*(?:,?\s*(?:and\s+)?(?:please\s+)?(?:give|provide|show|include)\s+(?:me\s+)?(?:an?\s+)?(?:everyday|real[- ]life|simple)?\s*examples?)\b.*$",
        r"\s*(?:,?\s*(?:and\s+)?(?:please\s+)?(?:give|provide|show|include)\s+(?:me\s+)?(?:an?\s+)?(?:code\s+)?examples?)\b.*$",
        r"\s+(?:in simple words|in simple terms|in easy words|in plain english|for beginners|briefly|in brief|in detail|with an example|with examples|with an everyday example|with a real[- ]life example)\s*[?.!]*$",
    )
    for pattern in directive_patterns:
        topic = re.sub(pattern, "", topic, flags=re.IGNORECASE).strip()

    # Strip a leading request verb or question phrase, but do not strip a leading
    # article from a proper topic such as "The Solar System".
    topic = re.sub(
        r"^(?:please\s+)?(?:can you\s+)?(?:explain|define|describe|tell me about|compare|difference between|what is|what are|what was|who is|who are|where is|where are|when is|when was|why is|why are|how does|how do|how is|how are)\s+",
        "", topic, flags=re.IGNORECASE,
    )
    topic = re.sub(r"[?.!]+$", "", topic).strip(" \t,;:")
    # Leading articles are request framing, not part of this canonical topic.
    topic = re.sub(r"^(?:the|a|an)\s+", "", topic, flags=re.IGNORECASE).strip()
    return topic[:180]


def _safe_public_http_url(value: Any) -> str:
    """Accept only absolute HTTP(S) URLs without embedded credentials."""
    url = str(value or "").strip()
    try:
        parsed = urlparse(url)
    except Exception:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    if parsed.username or parsed.password:
        return ""
    if len(url) > 2000:
        return ""
    host = parsed.hostname.lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        return ""
    return url


def store_search_evidence(db_path: str, evidence: Iterable[dict[str, Any]]) -> dict[str, int]:
    """Persist relevant search excerpts with explicit provenance and conservative licensing."""
    from brain.knowledge.open_knowledge import import_records

    records = []
    seen = set()
    for item in evidence or []:
        if not isinstance(item, dict):
            continue
        url = _safe_public_http_url(item.get("url") or item.get("provenance"))
        title = re.sub(r"\s+", " ", str(item.get("title") or "").strip())[:500]
        content = clean_evidence_text(item.get("content") or "")
        if not url or not title or len(content) < 40 or not is_useful_evidence(content):
            continue
        if re.search(r"(?i)\b(access denied|page not found|internal server error|search timed out)\b", content):
            continue
        key = url.casefold()
        if key in seen:
            continue
        seen.add(key)
        source_id = hashlib.sha256(url.encode("utf-8")).hexdigest()
        records.append({
            "source": "web_search",
            "source_id": source_id,
            "title": title,
            "content": content[:12000],
            "url": url,
            "language": "en",
            "license": "Search-result excerpt; original page license not established. See source URL.",
        })
    if not records:
        return {"accepted": 0, "processed": 0}
    result = import_records(db_path, records, limit=20, batch_size=20)
    return {"accepted": len(records), "processed": int(result.get("processed", 0))}


def fetch_and_store_wikimedia(topic: str, db_path: str) -> dict[str, Any]:
    """Fetch Wikipedia/Wikidata source records when general web search is unavailable."""
    from brain.knowledge.open_knowledge import fetch_and_store_topic

    normalized = topic_from_question(topic)
    if not normalized:
        return {"stored": 0, "reason": "empty_topic"}
    path = str(Path(db_path).expanduser())
    try:
        result = fetch_and_store_topic(path, normalized, language="en", timeout=8)
        LOG.info(
            "[OnlineKnowledge] Wikimedia topic acquisition completed topic=%r stored=%s",
            normalized, result.get("processed", result.get("stored", 0)),
        )
        return result
    except Exception as exc:
        LOG.warning("[OnlineKnowledge] Wikimedia acquisition failed for %r: %s", normalized, exc)
        return {"stored": 0, "reason": type(exc).__name__}
