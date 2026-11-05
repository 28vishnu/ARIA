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
    """Derive a concise search topic, including from long pasted-context prompts."""
    from brain.knowledge.query_planner import plan_knowledge_query

    topic = plan_knowledge_query(str(question or ""), max_chars=180)
    # Leading articles are request framing for search purposes.
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
