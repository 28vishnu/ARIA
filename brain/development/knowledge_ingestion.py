"""
ARIA Phase 1 — Step 8: Knowledge Ingestion.

Deterministic, provider-independent ingestion pipeline for ARIA knowledge.

Responsibilities:
- normalize incoming knowledge;
- split large content into bounded chunks;
- attach provenance and source metadata;
- validate records through KnowledgeArchitecture;
- avoid obvious duplicates;
- persist canonical records through KnowledgeDatabase;
- optionally create structured graph facts;
- provide deterministic ingestion statistics.

This module does not:
- call an LLM;
- perform web searches;
- answer user questions;
- retrieve knowledge;
- overwrite existing knowledge blindly.

Retrieval belongs to Step 9.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from brain.development.knowledge_architecture import (
    KnowledgeArchitecture,
    KnowledgeDomain,
    KnowledgeFreshness,
    KnowledgeKind,
    KnowledgeQuality,
    KnowledgeRecord,
    KnowledgeSource,
    Provenance,
    VerificationStatus,
)

logger = logging.getLogger("aria")


@dataclass(frozen=True)
class IngestionRequest:
    """Input contract for one knowledge-ingestion operation."""

    title: str
    content: str
    source_id: str

    domain: KnowledgeDomain = KnowledgeDomain.GENERAL
    kind: KnowledgeKind = KnowledgeKind.ARTICLE
    freshness: KnowledgeFreshness = KnowledgeFreshness.DURABLE

    source_uri: str | None = None
    source_name: str | None = None

    published_at: str | None = None
    source_version: str | None = None
    locator: str | None = None

    topics: tuple[str, ...] = ()
    entities: tuple[str, ...] = ()
    relations: tuple[str, ...] = ()

    metadata: Mapping[str, Any] = field(
        default_factory=dict
    )

    confidence: float = 0.70
    verification: VerificationStatus = (
        VerificationStatus.SOURCE_ATTESTED
    )

    chunk_size: int = 8000
    chunk_overlap: int = 400

    def __post_init__(self) -> None:
        if not str(self.title).strip():
            raise ValueError("title cannot be empty")

        if not str(self.content).strip():
            raise ValueError("content cannot be empty")

        if not str(self.source_id).strip():
            raise ValueError("source_id cannot be empty")

        object.__setattr__(
            self,
            "chunk_size",
            max(500, int(self.chunk_size)),
        )

        object.__setattr__(
            self,
            "chunk_overlap",
            max(
                0,
                min(
                    int(self.chunk_overlap),
                    self.chunk_size // 2,
                ),
            ),
        )

        object.__setattr__(
            self,
            "confidence",
            max(
                0.0,
                min(
                    1.0,
                    float(self.confidence),
                ),
            ),
        )


@dataclass(frozen=True)
class IngestionResult:
    """Machine-readable result of an ingestion operation."""

    accepted: bool
    knowledge_ids: tuple[str, ...] = ()
    duplicate_ids: tuple[str, ...] = ()
    rejected: tuple[str, ...] = ()
    chunks_created: int = 0
    records_stored: int = 0
    facts_created: int = 0
    source_id: str | None = None
    document_id: str | None = None

    @property
    def has_changes(self) -> bool:
        return self.records_stored > 0 or self.facts_created > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "knowledge_ids": list(self.knowledge_ids),
            "duplicate_ids": list(self.duplicate_ids),
            "rejected": list(self.rejected),
            "chunks_created": self.chunks_created,
            "records_stored": self.records_stored,
            "facts_created": self.facts_created,
            "source_id": self.source_id,
            "document_id": self.document_id,
            "has_changes": self.has_changes,
        }


class KnowledgeIngestion:
    """
    Canonical ingestion service for ARIA.

    The class is deliberately dependency-light. Any compatible database
    and graph implementation can be supplied, which keeps the architecture
    independent from MongoDB, ChromaDB and particular embedding providers.
    """

    VERSION = "PHASE1-KNOWLEDGE-INGESTION-20261004"

    DEFAULT_CHUNK_SIZE = 8000
    DEFAULT_CHUNK_OVERLAP = 400

    MAX_DOCUMENT_CHARS = 5_000_000
    MAX_TOPIC_COUNT = 50
    MAX_ENTITY_COUNT = 100
    MAX_RELATION_COUNT = 100

    def __init__(
        self,
        knowledge_database=None,
        knowledge_graph=None,
        architecture: KnowledgeArchitecture | None = None,
        source_registry: Iterable[KnowledgeSource] | None = None,
    ) -> None:

        self.database = knowledge_database
        self.graph = knowledge_graph

        self.architecture = (
            architecture
            or KnowledgeArchitecture(
                sources=source_registry
            )
            if source_registry is not None
            else architecture
            or KnowledgeArchitecture()
        )

        self.statistics = {
            "requests": 0,
            "accepted": 0,
            "rejected": 0,
            "duplicates": 0,
            "records_stored": 0,
            "chunks_created": 0,
            "facts_created": 0,
            "validation_failures": 0,
            "database_failures": 0,
            "graph_failures": 0,
        }

    # =========================================================
    # PUBLIC API
    # =========================================================

    async def ingest(
        self,
        request: IngestionRequest,
    ) -> IngestionResult:
        """
        Ingest one source document into canonical ARIA knowledge.

        The operation is deterministic and safe to retry:
        identical content produces the same document identity and chunk
        identities.
        """

        self.statistics["requests"] += 1

        if not isinstance(
            request,
            IngestionRequest,
        ):
            raise TypeError(
                "request must be an IngestionRequest"
            )

        content = self.normalize_text(
            request.content
        )

        if not content:
            self.statistics["rejected"] += 1

            return IngestionResult(
                accepted=False,
                rejected=("empty_content",),
                source_id=request.source_id,
            )

        if len(content) > self.MAX_DOCUMENT_CHARS:
            self.statistics["rejected"] += 1

            return IngestionResult(
                accepted=False,
                rejected=(
                    "document_exceeds_maximum_size",
                ),
                source_id=request.source_id,
            )

        source = self._resolve_source(
            request
        )

        if source is None:
            self.statistics["rejected"] += 1
            self.statistics["validation_failures"] += 1

            return IngestionResult(
                accepted=False,
                rejected=(
                    f"unknown_source:{request.source_id}",
                ),
                source_id=request.source_id,
            )

        document_id = self.document_id(
            source_id=request.source_id,
            content=content,
        )

        chunks = self.chunk_text(
            content=content,
            chunk_size=request.chunk_size,
            overlap=request.chunk_overlap,
        )

        if not chunks:
            self.statistics["rejected"] += 1

            return IngestionResult(
                accepted=False,
                rejected=("no_chunks_created",),
                source_id=request.source_id,
                document_id=document_id,
            )

        self.statistics["chunks_created"] += len(chunks)

        stored_ids: list[str] = []
        duplicate_ids: list[str] = []
        rejected: list[str] = []

        for index, chunk in enumerate(chunks):

            knowledge_id = self.chunk_id(
                document_id=document_id,
                chunk_index=index,
                content=chunk,
            )

            provenance = Provenance(
                source_id=source.source_id,
                source_name=(
                    request.source_name
                    or source.name
                ),
                source_uri=(
                    request.source_uri
                    or source.uri
                ),
                retrieved_at=self._utc_now(),
                published_at=request.published_at,
                source_version=request.source_version,
                locator=(
                    request.locator
                    or f"chunk:{index}"
                ),
                excerpt_hash=self.content_hash(
                    chunk
                ),
            )

            quality = KnowledgeQuality(
                confidence=request.confidence,
                source_authority=source.authority,
                relevance=0.70,
                completeness=(
                    1.0
                    if len(chunks) == 1
                    else 0.85
                ),
                verification=request.verification,
            )

            metadata = self._build_metadata(
                request=request,
                source=source,
                document_id=document_id,
                chunk_index=index,
                chunk_count=len(chunks),
            )

            record = KnowledgeRecord(
                knowledge_id=knowledge_id,
                title=self._chunk_title(
                    request.title,
                    index,
                    len(chunks),
                ),
                content=chunk,
                domain=request.domain,
                kind=(
                    KnowledgeKind.CHUNK
                    if len(chunks) > 1
                    else request.kind
                ),
                freshness=request.freshness,
                provenance=(provenance,),
                quality=quality,
                topics=self._clean_values(
                    request.topics,
                    self.MAX_TOPIC_COUNT,
                ),
                entities=self._clean_values(
                    request.entities,
                    self.MAX_ENTITY_COUNT,
                ),
                relations=self._clean_values(
                    request.relations,
                    self.MAX_RELATION_COUNT,
                ),
                parent_id=(
                    document_id
                    if len(chunks) > 1
                    else None
                ),
                chunk_index=(
                    index
                    if len(chunks) > 1
                    else None
                ),
                metadata=metadata,
            )

            errors = self.architecture.validate_record(
                record
            )

            if errors:
                self.statistics[
                    "validation_failures"
                ] += 1

                rejected.extend(
                    [
                        f"{knowledge_id}:{error}"
                        for error in errors
                    ]
                )

                continue

            if await self._is_duplicate(
                record
            ):
                self.statistics["duplicates"] += 1
                duplicate_ids.append(
                    knowledge_id
                )
                continue

            stored = await self._store_record(
                record
            )

            if not stored:
                rejected.append(
                    f"{knowledge_id}:storage_failed"
                )
                continue

            stored_ids.append(
                knowledge_id
            )

            self.statistics[
                "records_stored"
            ] += 1

        facts_created = await self._ingest_graph_facts(
            request=request,
            document_id=document_id,
        )

        self.statistics[
            "facts_created"
        ] += facts_created

        accepted = bool(
            stored_ids
            or duplicate_ids
        )

        if accepted:
            self.statistics["accepted"] += 1
        else:
            self.statistics["rejected"] += 1

        return IngestionResult(
            accepted=accepted,
            knowledge_ids=tuple(
                stored_ids
            ),
            duplicate_ids=tuple(
                duplicate_ids
            ),
            rejected=tuple(
                rejected
            ),
            chunks_created=len(chunks),
            records_stored=len(stored_ids),
            facts_created=facts_created,
            source_id=request.source_id,
            document_id=document_id,
        )

    async def ingest_text(
        self,
        title: str,
        content: str,
        source_id: str,
        **kwargs: Any,
    ) -> IngestionResult:
        """Convenience wrapper for plain text."""

        request = IngestionRequest(
            title=title,
            content=content,
            source_id=source_id,
            **kwargs,
        )

        return await self.ingest(
            request
        )

    async def ingest_document(
        self,
        filename: str,
        content: str,
        source_id: str = "aria_internal",
        metadata: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> IngestionResult:
        """
        Ingest a document while preserving filename metadata.

        Parsing/extraction of PDF/DOCX/etc. belongs to the document
        subsystem. This method receives already extracted text.
        """

        document_metadata = dict(
            metadata or {}
        )

        document_metadata.setdefault(
            "filename",
            filename,
        )

        return await self.ingest_text(
            title=filename,
            content=content,
            source_id=source_id,
            metadata=document_metadata,
            kind=KnowledgeKind.DOCUMENT,
            **kwargs,
        )

    async def ingest_web(
        self,
        title: str,
        content: str,
        source_id: str,
        uri: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> IngestionResult:
        """Ingest externally sourced information with explicit provenance."""

        return await self.ingest_text(
            title=title,
            content=content,
            source_id=source_id,
            source_uri=uri,
            metadata=metadata,
            freshness=KnowledgeFreshness.PERIODIC,
            **kwargs,
        )

    async def ingest_fact(
        self,
        subject: str,
        relation: str,
        value: str,
        source_id: str = "aria_internal",
        confidence: float = 0.80,
    ) -> IngestionResult:
        """
        Store a structured fact in the knowledge graph.

        The graph is authoritative for relationship structure; a canonical
        textual record is also stored so the fact participates in ordinary
        knowledge retrieval later.
        """

        subject = self.normalize_text(
            subject
        )
        relation = self.normalize_text(
            relation
        )
        value = self.normalize_text(
            value
        )

        if not subject or not relation or not value:
            return IngestionResult(
                accepted=False,
                rejected=("invalid_fact",),
                source_id=source_id,
            )

        text = (
            f"{subject} {relation} {value}."
        )

        result = await self.ingest_text(
            title=(
                f"{subject} — {relation}"
            ),
            content=text,
            source_id=source_id,
            kind=KnowledgeKind.RELATION,
            confidence=confidence,
            relations=(relation,),
            entities=(
                subject,
                value,
            ),
        )

        if (
            self.graph is not None
            and result.accepted
        ):
            try:
                await self.graph.add_fact(
                    subject,
                    relation,
                    value,
                )
            except Exception:
                self.statistics[
                    "graph_failures"
                ] += 1

                logger.exception(
                    "[KnowledgeIngestion] "
                    "Failed to add graph fact."
                )

        return result

    # =========================================================
    # NORMALIZATION
    # =========================================================

    @staticmethod
    def normalize_text(
        value: Any,
    ) -> str:
        """
        Normalize text without destroying meaningful punctuation.

        Whitespace is canonicalized while paragraph boundaries are kept.
        """

        text = str(
            value or ""
        ).replace(
            "\x00",
            " ",
        )

        text = text.replace(
            "\r\n",
            "\n",
        ).replace(
            "\r",
            "\n",
        )

        lines = [
            re.sub(
                r"[ \t]+",
                " ",
                line,
            ).strip()
            for line in text.split("\n")
        ]

        output: list[str] = []

        blank_seen = False

        for line in lines:

            if not line:
                if not blank_seen:
                    output.append("")
                blank_seen = True
                continue

            output.append(line)
            blank_seen = False

        return "\n".join(
            output
        ).strip()

    @staticmethod
    def content_hash(
        content: str,
    ) -> str:
        """Return a stable SHA-256 content fingerprint."""

        normalized = (
            KnowledgeIngestion.normalize_text(
                content
            )
        )

        return hashlib.sha256(
            normalized.encode(
                "utf-8"
            )
        ).hexdigest()

    @classmethod
    def document_id(
        cls,
        source_id: str,
        content: str,
    ) -> str:
        digest = hashlib.sha256(
            (
                f"{source_id.strip()}:"
                f"{cls.content_hash(content)}"
            ).encode(
                "utf-8"
            )
        ).hexdigest()

        return f"doc_{digest[:32]}"

    @classmethod
    def chunk_id(
        cls,
        document_id: str,
        chunk_index: int,
        content: str,
    ) -> str:
        digest = hashlib.sha256(
            (
                f"{document_id}:"
                f"{chunk_index}:"
                f"{cls.content_hash(content)}"
            ).encode(
                "utf-8"
            )
        ).hexdigest()

        return f"know_{digest[:32]}"

    # =========================================================
    # CHUNKING
    # =========================================================

    @classmethod
    def chunk_text(
        cls,
        content: str,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        overlap: int = DEFAULT_CHUNK_OVERLAP,
    ) -> list[str]:
        """
        Split text into bounded chunks while preferring paragraph,
        sentence and whitespace boundaries.

        The algorithm is deterministic and never calls an LLM.
        """

        text = cls.normalize_text(
            content
        )

        if not text:
            return []

        chunk_size = max(
            500,
            int(chunk_size),
        )

        overlap = max(
            0,
            min(
                int(overlap),
                chunk_size // 2,
            ),
        )

        if len(text) <= chunk_size:
            return [text]

        chunks: list[str] = []

        start = 0
        text_length = len(text)

        while start < text_length:

            hard_end = min(
                start + chunk_size,
                text_length,
            )

            if hard_end >= text_length:
                chunk = text[start:].strip()

                if chunk:
                    chunks.append(
                        chunk
                    )

                break

            boundary = cls._find_boundary(
                text,
                start,
                hard_end,
            )

            if boundary <= start:
                boundary = hard_end

            chunk = text[
                start:boundary
            ].strip()

            if chunk:
                chunks.append(
                    chunk
                )

            next_start = max(
                boundary - overlap,
                start + 1,
            )

            start = next_start

        return cls._deduplicate_adjacent(
            chunks
        )

    @staticmethod
    def _find_boundary(
        text: str,
        start: int,
        end: int,
    ) -> int:
        window = text[
            start:end
        ]

        paragraph = window.rfind(
            "\n\n"
        )

        if paragraph > int(
            len(window) * 0.55
        ):
            return start + paragraph + 2

        sentence_matches = list(
            re.finditer(
                r"[.!?](?:\s+|$)",
                window,
            )
        )

        if sentence_matches:
            candidate = sentence_matches[-1]

            if candidate.end() > int(
                len(window) * 0.55
            ):
                return start + candidate.end()

        whitespace = window.rfind(
            " "
        )

        if whitespace > int(
            len(window) * 0.55
        ):
            return start + whitespace + 1

        return end

    @staticmethod
    def _deduplicate_adjacent(
        chunks: Sequence[str],
    ) -> list[str]:
        result: list[str] = []

        previous_hash = None

        for chunk in chunks:

            digest = hashlib.sha256(
                chunk.encode(
                    "utf-8"
                )
            ).hexdigest()

            if digest == previous_hash:
                continue

            result.append(
                chunk
            )

            previous_hash = digest

        return result

    # =========================================================
    # SOURCE / RECORD HELPERS
    # =========================================================

    def _resolve_source(
        self,
        request: IngestionRequest,
    ) -> KnowledgeSource | None:

        source = self.architecture.get_source(
            request.source_id
        )

        if source is None:
            return None

        if not source.enabled:
            return None

        return source

    @staticmethod
    def _utc_now() -> str:
        return (
            datetime.now(
                timezone.utc
            )
            .isoformat()
        )

    @staticmethod
    def _clean_values(
        values: Iterable[Any],
        maximum: int,
    ) -> tuple[str, ...]:

        result: list[str] = []
        seen: set[str] = set()

        for value in values:

            normalized = (
                KnowledgeIngestion.normalize_text(
                    value
                )
            )

            if not normalized:
                continue

            key = normalized.casefold()

            if key in seen:
                continue

            seen.add(key)
            result.append(
                normalized
            )

            if len(result) >= maximum:
                break

        return tuple(
            result
        )

    @staticmethod
    def _chunk_title(
        title: str,
        index: int,
        count: int,
    ) -> str:

        title = (
            KnowledgeIngestion.normalize_text(
                title
            )
        )

        if count <= 1:
            return title

        return (
            f"{title} "
            f"[Part {index + 1}/{count}]"
        )

    def _build_metadata(
        self,
        request: IngestionRequest,
        source: KnowledgeSource,
        document_id: str,
        chunk_index: int,
        chunk_count: int,
    ) -> dict[str, Any]:

        metadata = dict(
            request.metadata
        )

        metadata.update(
            {
                "ingestion_version": self.VERSION,
                "source_id": source.source_id,
                "document_id": document_id,
                "chunk_index": chunk_index,
                "chunk_count": chunk_count,
                "ingested_at": self._utc_now(),
            }
        )

        return metadata

    # =========================================================
    # DUPLICATE DETECTION
    # =========================================================

    async def _is_duplicate(
        self,
        record: KnowledgeRecord,
    ) -> bool:

        if self.database is None:
            return False

        content_hash = self.content_hash(
            record.content
        )

        # Preferred deterministic lookup.
        for method_name in (
            "exists",
            "find_related",
        ):

            method = getattr(
                self.database,
                method_name,
                None,
            )

            if method is None:
                continue

            try:

                if method_name == "exists":

                    result = method(
                        record.knowledge_id
                    )

                    if hasattr(
                        result,
                        "__await__",
                    ):
                        result = await result

                    if result:
                        return True

                else:

                    result = method(
                        record.content,
                        limit=3,
                    )

                    if hasattr(
                        result,
                        "__await__",
                    ):
                        result = await result

                    if result:

                        for item in (
                            result
                            if isinstance(
                                result,
                                list,
                            )
                            else [result]
                        ):

                            metadata = (
                                item.get(
                                    "metadata",
                                    {},
                                )
                                if isinstance(
                                    item,
                                    dict,
                                )
                                else {}
                            )

                            if (
                                metadata.get(
                                    "content_hash"
                                )
                                == content_hash
                            ):
                                return True

            except Exception:
                logger.debug(
                    "[KnowledgeIngestion] "
                    "Duplicate lookup %s failed.",
                    method_name,
                    exc_info=True,
                )

        return False

    # =========================================================
    # STORAGE
    # =========================================================

    async def _store_record(
        self,
        record: KnowledgeRecord,
    ) -> bool:

        if self.database is None:
            logger.warning(
                "[KnowledgeIngestion] "
                "No knowledge database configured."
            )
            self.statistics[
                "database_failures"
            ] += 1
            return False

        store = getattr(
            self.database,
            "store",
            None,
        )

        if store is None:
            self.statistics[
                "database_failures"
            ] += 1
            return False

        metadata = dict(
            record.metadata
        )

        metadata.setdefault(
            "content_hash",
            self.content_hash(
                record.content
            ),
        )

        metadata.setdefault(
            "knowledge_id",
            record.knowledge_id,
        )

        metadata.setdefault(
            "domain",
            record.domain.value,
        )

        metadata.setdefault(
            "kind",
            record.kind.value,
        )

        metadata.setdefault(
            "freshness",
            record.freshness.value,
        )

        provenance = (
            record.provenance[0]
            if record.provenance
            else None
        )

        source = (
            provenance.source_id
            if provenance
            else "unknown"
        )

        try:

            result = store(
                title=record.title,
                content=record.content,
                source=source,
                metadata=metadata,
            )

            if hasattr(
                result,
                "__await__",
            ):
                await result

            return True

        except Exception:
            self.statistics[
                "database_failures"
            ] += 1

            logger.exception(
                "[KnowledgeIngestion] "
                "Knowledge database storage failed."
            )

            return False

    # =========================================================
    # GRAPH INGESTION
    # =========================================================

    async def _ingest_graph_facts(
        self,
        request: IngestionRequest,
        document_id: str,
    ) -> int:

        if self.graph is None:
            return 0

        add_fact = getattr(
            self.graph,
            "add_fact",
            None,
        )

        if add_fact is None:
            return 0

        facts_created = 0

        for relation in self._clean_values(
            request.relations,
            self.MAX_RELATION_COUNT,
        ):

            if not request.entities:
                continue

            subject = str(
                request.entities[0]
            ).strip()

            if not subject:
                continue

            try:

                await add_fact(
                    subject,
                    relation,
                    document_id,
                )

                facts_created += 1

            except Exception:
                self.statistics[
                    "graph_failures"
                ] += 1

                logger.exception(
                    "[KnowledgeIngestion] "
                    "Graph fact ingestion failed."
                )

        return facts_created

    # =========================================================
    # TELEMETRY
    # =========================================================

    def statistics_summary(
        self,
    ) -> dict[str, Any]:

        return {
            "version": self.VERSION,
            **self.statistics,
        }

    def describe(
        self,
    ) -> dict[str, Any]:

        return {
            "version": self.VERSION,
            "role": (
                "canonical knowledge ingestion"
            ),
            "properties": [
                "deterministic",
                "idempotent",
                "provenance-aware",
                "chunk-aware",
                "quality-aware",
                "graph-compatible",
                "provider-independent",
            ],
            "limits": {
                "max_document_chars": (
                    self.MAX_DOCUMENT_CHARS
                ),
                "default_chunk_size": (
                    self.DEFAULT_CHUNK_SIZE
                ),
                "default_chunk_overlap": (
                    self.DEFAULT_CHUNK_OVERLAP
                ),
            },
            "next_step": (
                "knowledge retrieval"
            ),
        }


__all__ = [
    "IngestionRequest",
    "IngestionResult",
    "KnowledgeIngestion",
]