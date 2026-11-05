"""
ARIA Phase 1 — Step 25: Knowledge → Coding Feedback Loop.

Connects ARIA's existing knowledge retrieval system with its autonomous
software-development system.

Flow:

    requirement
        ↓
    knowledge retrieval
        ↓
    evidence normalization
        ↓
    coding guidance/context
        ↓
    repository/code generation
        ↓
    validation/repair
        ↓
    outcome can later be learned

This module is intentionally an orchestration adapter.

It does NOT:
    - generate code;
    - modify files;
    - execute shell commands;
    - call GitHub;
    - deploy;
    - replace KnowledgeRetriever;
    - replace CodingContextSelector.

Those systems remain the owners of their respective responsibilities.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class CodingEvidence:
    """
    One normalized piece of knowledge supplied to development.
    """

    content: str
    source: str = "unknown"
    confidence: float = 0.0
    relevance: float = 0.0
    verified: bool = False
    evidence_type: str = "unknown"
    provenance: str | None = None
    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "source": self.source,
            "confidence": self.confidence,
            "relevance": self.relevance,
            "verified": self.verified,
            "evidence_type": self.evidence_type,
            "provenance": self.provenance,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class CodingKnowledgeContext:
    """
    Bounded knowledge context prepared for coding.
    """

    query: str
    evidence: tuple[CodingEvidence, ...] = ()
    sources_used: tuple[str, ...] = ()
    retrieval_errors: tuple[str, ...] = ()
    has_evidence: bool = False
    context_text: str = ""
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "evidence": [
                item.to_dict()
                for item in self.evidence
            ],
            "sources_used": list(
                self.sources_used
            ),
            "retrieval_errors": list(
                self.retrieval_errors
            ),
            "has_evidence": self.has_evidence,
            "context_text": self.context_text,
            "confidence": self.confidence,
        }


class KnowledgeCodingFeedback:
    """
    Adapter between KnowledgeRetriever and autonomous development.

    The adapter intentionally accepts the retriever through dependency
    injection so ARIA can use:

        brain.memory.KnowledgeRetriever

    or another compatible retrieval implementation without changing
    the development architecture.
    """

    VERSION = (
        "PHASE1-KNOWLEDGE-CODING-FEEDBACK-20261004"
    )

    DEFAULT_LIMIT = 8
    MAX_LIMIT = 20
    MAX_CONTEXT_CHARS = 24_000
    MAX_EVIDENCE_CHARS = 5_000

    def __init__(
        self,
        knowledge_retriever=None,
        *,
        max_context_chars: int = MAX_CONTEXT_CHARS,
    ) -> None:

        if knowledge_retriever is None:
            raise ValueError(
                "knowledge_retriever is required."
            )

        self.retriever = knowledge_retriever

        self.max_context_chars = max(
            2_000,
            int(max_context_chars),
        )

        self._last_context: (
            CodingKnowledgeContext | None
        ) = None

    # ==========================================================
    # NORMALIZATION
    # ==========================================================

    @staticmethod
    def _clean_text(value: Any) -> str:
        text = str(value or "").strip()

        text = re.sub(
            r"\s+",
            " ",
            text,
        )

        return text

    @staticmethod
    def _score(
        item: Mapping[str, Any],
    ) -> float:

        try:
            relevance = float(
                item.get(
                    "relevance",
                    0.0,
                )
            )
        except Exception:
            relevance = 0.0

        try:
            confidence = float(
                item.get(
                    "confidence",
                    0.0,
                )
            )
        except Exception:
            confidence = 0.0

        verified = bool(
            item.get(
                "verified",
                False,
            )
        )

        score = (
            max(
                0.0,
                min(
                    1.0,
                    relevance,
                ),
            )
            * 0.60
        )

        score += (
            max(
                0.0,
                min(
                    1.0,
                    confidence,
                ),
            )
            * 0.30
        )

        if verified:
            score += 0.10

        return score

    @classmethod
    def _normalize_item(
        cls,
        item: Any,
    ) -> CodingEvidence | None:

        if isinstance(
            item,
            CodingEvidence,
        ):
            return item

        if isinstance(
            item,
            str,
        ):
            content = cls._clean_text(
                item
            )

            if not content:
                return None

            return CodingEvidence(
                content=content,
                source="retrieval",
                confidence=0.50,
                relevance=0.50,
            )

        if not isinstance(
            item,
            Mapping,
        ):
            return None

        content = cls._clean_text(
            item.get(
                "content",
                item.get(
                    "text",
                    item.get(
                        "summary",
                        "",
                    ),
                ),
            )
        )

        if not content:
            return None

        try:
            confidence = float(
                item.get(
                    "confidence",
                    0.0,
                )
            )
        except Exception:
            confidence = 0.0

        try:
            relevance = float(
                item.get(
                    "relevance",
                    0.0,
                )
            )
        except Exception:
            relevance = 0.0

        metadata = item.get(
            "metadata",
            {},
        )

        if not isinstance(
            metadata,
            Mapping,
        ):
            metadata = {}

        return CodingEvidence(
            content=content,
            source=str(
                item.get(
                    "source",
                    item.get(
                        "source_id",
                        "retrieval",
                    ),
                )
            ),
            confidence=max(
                0.0,
                min(
                    1.0,
                    confidence,
                ),
            ),
            relevance=max(
                0.0,
                min(
                    1.0,
                    relevance,
                ),
            ),
            verified=bool(
                item.get(
                    "verified",
                    False,
                )
            ),
            evidence_type=str(
                item.get(
                    "evidence_type",
                    item.get(
                        "kind",
                        "unknown",
                    ),
                )
            ),
            provenance=(
                str(
                    item["provenance"]
                )
                if item.get("provenance")
                else None
            ),
            metadata=dict(
                metadata
            ),
        )

    # ==========================================================
    # RESULT COLLECTION
    # ==========================================================

    @classmethod
    def _collect_evidence(
        cls,
        retrieval: Mapping[str, Any],
        limit: int,
    ) -> list[CodingEvidence]:

        evidence: list[CodingEvidence] = []

        ordered_keys = (
            "knowledge",
            "document_knowledge",
            "graph_knowledge",
            "personal_memories",
            "conversation_context",
        )

        for key in ordered_keys:

            values = retrieval.get(
                key,
                [],
            )

            if not isinstance(
                values,
                Sequence,
            ) or isinstance(
                values,
                (str, bytes),
            ):
                continue

            for raw_item in values:

                normalized = (
                    cls._normalize_item(
                        raw_item
                    )
                )

                if normalized is None:
                    continue

                evidence.append(
                    normalized
                )

        # Highest quality/relevance evidence first.
        evidence.sort(
            key=lambda item: (
                -cls._score(
                    item.to_dict()
                ),
                -item.relevance,
                -item.confidence,
                item.source,
            )
        )

        # Deduplicate by normalized content.
        unique: list[CodingEvidence] = []
        seen: set[str] = set()

        for item in evidence:

            identity = re.sub(
                r"\s+",
                " ",
                item.content.lower(),
            )

            if identity in seen:
                continue

            seen.add(identity)
            unique.append(item)

            if len(unique) >= limit:
                break

        return unique

    # ==========================================================
    # CONTEXT BUILDING
    # ==========================================================

    def _build_context_text(
        self,
        evidence: Sequence[CodingEvidence],
    ) -> str:

        if not evidence:
            return ""

        sections: list[str] = [
            "RELEVANT ARIA KNOWLEDGE FOR THIS DEVELOPMENT TASK:",
            "",
        ]

        current_chars = len(
            sections[0]
        ) + 2

        for index, item in enumerate(
            evidence,
            start=1,
        ):

            content = item.content[
                : self.MAX_EVIDENCE_CHARS
            ]

            section = (
                f"[Evidence {index}]\n"
                f"Source: {item.source}\n"
                f"Type: {item.evidence_type}\n"
                f"Confidence: "
                f"{item.confidence:.2f}\n"
                f"Relevance: "
                f"{item.relevance:.2f}\n"
                f"Verified: "
                f"{item.verified}\n"
                f"Content: {content}\n"
            )

            section_size = len(section)

            if (
                current_chars
                + section_size
                > self.max_context_chars
            ):
                break

            sections.append(section)

            current_chars += section_size

        return "\n".join(
            sections
        ).strip()

    # ==========================================================
    # MAIN API
    # ==========================================================

    async def prepare(
        self,
        requirement: str,
        *,
        user_id: str = "",
        session_id: str = "",
        coding_context: Mapping[str, Any] | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> CodingKnowledgeContext:
        """
        Retrieve and prepare knowledge for a coding task.

        The returned context can be merged into the existing development
        context before code generation.
        """

        query = self._clean_text(
            requirement
        )

        if not query:
            result = CodingKnowledgeContext(
                query="",
                has_evidence=False,
            )

            self._last_context = result

            return result

        safe_limit = max(
            1,
            min(
                int(limit),
                self.MAX_LIMIT,
            ),
        )

        retrieval = await self.retriever.retrieve(
            query=query,
            user_id=user_id,
            session_id=session_id,
            context=dict(
                coding_context or {}
            ),
            limit=safe_limit,
            include_memory=True,
            include_documents=True,
            include_graph=True,
        )

        if not isinstance(
            retrieval,
            Mapping,
        ):
            retrieval = {}

        evidence = self._collect_evidence(
            retrieval,
            safe_limit,
        )

        context_text = (
            self._build_context_text(
                evidence
            )
        )

        sources = tuple(
            dict.fromkeys(
                item.source
                for item in evidence
                if item.source
            )
        )

        raw_errors = retrieval.get(
            "retrieval_errors",
            [],
        )

        retrieval_errors: list[str] = []

        if isinstance(
            raw_errors,
            Sequence,
        ) and not isinstance(
            raw_errors,
            (str, bytes),
        ):
            for error in raw_errors:

                if isinstance(
                    error,
                    Mapping,
                ):
                    message = error.get(
                        "error",
                        error,
                    )
                else:
                    message = error

                text = self._clean_text(
                    message
                )

                if text:
                    retrieval_errors.append(
                        text
                    )

        if evidence:
            confidence = sum(
                item.confidence
                for item in evidence
            ) / len(evidence)

        else:
            confidence = 0.0

        result = CodingKnowledgeContext(
            query=query,
            evidence=tuple(
                evidence
            ),
            sources_used=sources,
            retrieval_errors=tuple(
                retrieval_errors
            ),
            has_evidence=bool(
                evidence
            ),
            context_text=context_text,
            confidence=round(
                confidence,
                4,
            ),
        )

        self._last_context = result

        return result

    # ==========================================================
    # CONTEXT MERGING
    # ==========================================================

    def merge_into(
        self,
        development_context: Mapping[str, Any] | None,
        knowledge_context: CodingKnowledgeContext,
    ) -> dict[str, Any]:
        """
        Merge retrieved knowledge into an existing development context.

        Existing repository/planning data is preserved.

        The knowledge layer is additive and namespaced so lower-level
        development components do not accidentally overwrite their own
        fields.
        """

        merged = dict(
            development_context or {}
        )

        existing_knowledge = merged.get(
            "knowledge",
            {},
        )

        if not isinstance(
            existing_knowledge,
            Mapping,
        ):
            existing_knowledge = {}

        merged["knowledge"] = {
            **dict(existing_knowledge),
            "version": self.VERSION,
            "query": knowledge_context.query,
            "has_evidence": (
                knowledge_context.has_evidence
            ),
            "confidence": (
                knowledge_context.confidence
            ),
            "sources_used": list(
                knowledge_context.sources_used
            ),
            "retrieval_errors": list(
                knowledge_context.retrieval_errors
            ),
            "evidence": [
                item.to_dict()
                for item in knowledge_context.evidence
            ],
            "coding_guidance": (
                knowledge_context.context_text
            ),
        }

        return merged

    async def enrich(
        self,
        development_context: Mapping[str, Any] | None,
        requirement: str,
        *,
        user_id: str = "",
        session_id: str = "",
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        """
        One-call convenience API:

            retrieve → normalize → merge

        This is the main API future autonomous planning/execution code
        can call before code generation.
        """

        knowledge_context = await self.prepare(
            requirement,
            user_id=user_id,
            session_id=session_id,
            coding_context=development_context,
            limit=limit,
        )

        return self.merge_into(
            development_context,
            knowledge_context,
        )

    # ==========================================================
    # INSPECTION
    # ==========================================================

    def status(self) -> dict[str, Any]:
        return {
            "version": self.VERSION,
            "has_retriever": (
                self.retriever is not None
            ),
            "max_context_chars": (
                self.max_context_chars
            ),
            "last_context": (
                self._last_context.to_dict()
                if self._last_context is not None
                else None
            ),
        }

    def health(self) -> dict[str, Any]:
        return {
            "healthy": (
                self.retriever is not None
            ),
            "has_last_context": (
                self._last_context is not None
            ),
        }

    def describe(self) -> dict[str, Any]:
        return {
            "name": "knowledge_coding_feedback",
            "purpose": (
                "Feed relevant retrieved knowledge into autonomous "
                "software-development context."
            ),
            "retrieval_owner": (
                "brain.memory.knowledge_retriever"
            ),
            "coding_owner": (
                "brain.development"
            ),
            "writes_files": False,
            "executes_code": False,
            "github_push": False,
            "deployment": False,
        }


__all__ = [
    "CodingEvidence",
    "CodingKnowledgeContext",
    "KnowledgeCodingFeedback",
]