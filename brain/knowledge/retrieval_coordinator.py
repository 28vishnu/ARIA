"""Deterministic local-first evidence retrieval coordinator for ARIA."""
from __future__ import annotations

import inspect
import logging
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger("aria")


@dataclass
class RetrievalOutcome:
    evidence: List[Dict[str, Any]]
    local_evidence_count: int
    used_online: bool
    normalized_query: str


class RetrievalCoordinator:
    """Try local evidence first; use a configured search adapter only on a miss."""

    STOP_WORDS = {
        "what", "who", "where", "when", "why", "how", "is", "are", "was", "were",
        "the", "a", "an", "of", "for", "to", "and", "or", "in", "on", "with",
        "me", "us", "please", "explain", "define", "describe", "tell", "about",
        "using", "your", "locally", "stored", "knowledge", "provide", "give", "source",
        "url", "answer", "simple", "words", "terms", "detail", "briefly", "brief",
        "example", "examples", "real", "life", "everyday", "include", "show",
    }

    _PREFIX = re.compile(
        r"^(?:(?:please\s+)?(?:answer|explain|define|describe|tell me about)\s+|"
        r"what(?:'s| is| are| was| were| does| do)\s+|who(?:'s| is| are)\s+|"
        r"where(?:'s| is| are)\s+|when(?:'s| is| was)\s+|why(?: is| are| does| do)\s+|"
        r"how(?: is| are| does| do)\s+|difference between\s+|compare\s+)+",
        re.IGNORECASE,
    )

    @classmethod
    def normalize_query(cls, question: str) -> str:
        """Strip request-style wording while preserving the actual topic."""
        q = re.sub(r"\s+", " ", str(question or "").strip()).replace("’", "'")
        q = re.sub(r"(?i)^answer\s+using\s+(?:your\s+)?(?:locally\s+stored\s+)?knowledge\s*:?\s*(?:and\s+)?", "", q)
        q = re.sub(r"(?i)\b(?:and\s+)?(?:provide|give|include|show)\s+(?:me\s+)?(?:the\s+)?(?:source(?:\s+url)?|url|citations?)\b.*$", "", q)
        q = re.sub(r"(?i)\b(?:in simple words|in simple terms|in easy words|for beginners|in detail|in brief|briefly|in short)\b.*$", "", q)
        q = re.sub(r"(?i)\b(?:please|answer using your local(?:ly stored)? knowledge)\b", "", q)
        q = cls._PREFIX.sub("", q).strip(" \t.,;:!?-–—")
        q = re.sub(r"\s+", " ", q)
        return q or re.sub(r"[?!]+$", "", str(question or "").strip()).strip()

    async def retrieve(
        self,
        question: str,
        local_retriever: Callable[[str], Awaitable[List[Dict[str, Any]]]],
        online_retriever: Callable[[str], Awaitable[List[Dict[str, Any]]]],
        is_sufficient: Callable[..., bool],
    ) -> RetrievalOutcome:
        normalized = self.normalize_query(question)
        local: List[Dict[str, Any]] = []
        try:
            local_result = await local_retriever(question)
            if isinstance(local_result, list):
                local = local_result
        except Exception:
            logger.exception("[RetrievalCoordinator] Local retrieval failed; checking configured fallback.")

        sufficient = False
        try:
            sufficient = bool(is_sufficient(local, normalized))
        except TypeError:
            sufficient = bool(is_sufficient(local))
        except Exception:
            logger.exception("[RetrievalCoordinator] Evidence sufficiency check failed; treating local result as insufficient.")

        if sufficient:
            return RetrievalOutcome(local, len(local), False, normalized)

        logger.info(
            "[RetrievalCoordinator] Local evidence insufficient (%d records); attempting configured search for normalized topic %r.",
            len(local), normalized,
        )
        online: List[Dict[str, Any]] = []
        try:
            online_result = await online_retriever(normalized)
            if isinstance(online_result, list):
                online = online_result
        except Exception:
            logger.exception("[RetrievalCoordinator] Configured online retrieval failed.")

        # When local evidence failed the sufficiency gate, do not pass it to the
        # answer composer: irrelevant fragments can contaminate a grounded answer.
        # Keep only online evidence until a later evidence-validation step can
        # selectively merge partial local matches.
        combined: List[Dict[str, Any]] = []
        seen = set()
        for item in online:
            if not isinstance(item, dict):
                continue
            key = (str(item.get("url") or item.get("source_url") or ""),
                   re.sub(r"\s+", " ", str(item.get("content") or "").casefold()).strip())
            if key in seen:
                continue
            seen.add(key)
            combined.append(item)
        return RetrievalOutcome(combined, len(local), bool(online), normalized)
