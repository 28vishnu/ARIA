"""
ARIA Phase 1 — Step 7: Knowledge Architecture.

Defines the stable, provider-independent architecture for ARIA's durable
knowledge foundation. This module is intentionally read-only with respect
to external knowledge sources: it describes sources, records, provenance,
quality, lifecycle and storage contracts. Ingestion and retrieval are
implemented in later Phase 1 steps.

Design goals:
- separate foundational knowledge from personal/episodic memory;
- preserve source and provenance information;
- support text, documents, structured records and knowledge-graph facts;
- allow local-first storage and embeddings;
- keep current/live information separate from durable knowledge;
- make later ingestion/retrieval deterministic and auditable;
- avoid coupling the architecture to MongoDB, ChromaDB, a specific model,
  Wikipedia, Wikidata or any single external provider.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping


class KnowledgeDomain(str, Enum):
    """High-level durable knowledge domains."""

    PROGRAMMING = "programming"
    COMPUTER_SCIENCE = "computer_science"
    MATHEMATICS = "mathematics"
    SCIENCE = "science"
    ENGINEERING = "engineering"
    ARTIFICIAL_INTELLIGENCE = "artificial_intelligence"
    EDUCATION = "education"
    GENERAL = "general"
    ARIA = "aria"
    DOCUMENT = "document"
    OTHER = "other"


class KnowledgeKind(str, Enum):
    """Shape of information stored in the knowledge foundation."""

    ARTICLE = "article"
    DOCUMENT = "document"
    FACT = "fact"
    CONCEPT = "concept"
    PROCEDURE = "procedure"
    CODE_REFERENCE = "code_reference"
    API_REFERENCE = "api_reference"
    Q_AND_A = "q_and_a"
    ENTITY = "entity"
    RELATION = "relation"
    CHUNK = "chunk"


class KnowledgeFreshness(str, Enum):
    """Whether a record is intended to remain valid over time."""

    DURABLE = "durable"
    PERIODIC = "periodic"
    CURRENT = "current"
    UNKNOWN = "unknown"


class VerificationStatus(str, Enum):
    """Evidence/verification state of a knowledge record."""

    UNVERIFIED = "unverified"
    SOURCE_ATTESTED = "source_attested"
    CROSS_CHECKED = "cross_checked"
    VERIFIED = "verified"
    CONFLICTED = "conflicted"
    RETIRED = "retired"


@dataclass(frozen=True)
class KnowledgeSource:
    """Canonical description of one knowledge source."""

    source_id: str
    name: str
    source_type: str
    authority: float = 0.5
    freshness: KnowledgeFreshness = KnowledgeFreshness.UNKNOWN
    domains: tuple[str, ...] = ()
    uri: str | None = None
    enabled: bool = True
    ingestion_policy: str = "manual_or_scheduled"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "authority",
            max(
                0.0,
                min(
                    1.0,
                    float(self.authority),
                ),
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)

        value["freshness"] = self.freshness.value
        value["domains"] = list(self.domains)
        value["metadata"] = dict(self.metadata)

        return value


@dataclass(frozen=True)
class Provenance:
    """Evidence chain for a knowledge record."""

    source_id: str
    source_name: str
    source_uri: str | None = None
    retrieved_at: str | None = None
    published_at: str | None = None
    source_version: str | None = None
    locator: str | None = None
    excerpt_hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class KnowledgeQuality:
    """Quality signals kept with every durable knowledge item."""

    confidence: float = 0.5
    source_authority: float = 0.5
    relevance: float = 0.5
    completeness: float = 0.5
    verification: VerificationStatus = VerificationStatus.UNVERIFIED
    conflict_count: int = 0

    def __post_init__(self) -> None:
        for name in (
            "confidence",
            "source_authority",
            "relevance",
            "completeness",
        ):
            object.__setattr__(
                self,
                name,
                max(
                    0.0,
                    min(
                        1.0,
                        float(getattr(self, name)),
                    ),
                ),
            )

        object.__setattr__(
            self,
            "conflict_count",
            max(
                0,
                int(self.conflict_count),
            ),
        )

    def score(self) -> float:
        """Return a deterministic composite quality score."""

        base = (
            self.confidence * 0.35
            + self.source_authority * 0.30
            + self.relevance * 0.20
            + self.completeness * 0.15
        )

        penalty = min(
            0.25,
            self.conflict_count * 0.05,
        )

        return max(
            0.0,
            min(
                1.0,
                base - penalty,
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)

        value["verification"] = self.verification.value
        value["score"] = self.score()

        return value


@dataclass(frozen=True)
class KnowledgeRecord:
    """Provider-independent canonical knowledge record."""

    knowledge_id: str
    title: str
    content: str

    domain: KnowledgeDomain = KnowledgeDomain.GENERAL
    kind: KnowledgeKind = KnowledgeKind.ARTICLE
    freshness: KnowledgeFreshness = KnowledgeFreshness.DURABLE

    provenance: tuple[Provenance, ...] = ()

    quality: KnowledgeQuality = field(
        default_factory=KnowledgeQuality
    )

    topics: tuple[str, ...] = ()
    entities: tuple[str, ...] = ()
    relations: tuple[str, ...] = ()

    parent_id: str | None = None
    chunk_index: int | None = None

    metadata: Mapping[str, Any] = field(
        default_factory=dict
    )

    active: bool = True

    def normalized_text(self) -> str:
        """Return a deterministic normalized representation for indexing."""

        return " ".join(
            str(self.content).split()
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "knowledge_id": self.knowledge_id,
            "title": self.title,
            "content": self.content,
            "domain": self.domain.value,
            "kind": self.kind.value,
            "freshness": self.freshness.value,
            "provenance": [
                item.to_dict()
                for item in self.provenance
            ],
            "quality": self.quality.to_dict(),
            "topics": list(self.topics),
            "entities": list(self.entities),
            "relations": list(self.relations),
            "parent_id": self.parent_id,
            "chunk_index": self.chunk_index,
            "metadata": dict(self.metadata),
            "active": self.active,
        }


@dataclass(frozen=True)
class KnowledgeQuery:
    """Provider-independent retrieval request used by later Step 9."""

    query: str

    domains: tuple[str, ...] = ()
    kinds: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()

    limit: int = 5
    min_quality: float = 0.0

    include_current: bool = False
    include_documents: bool = True
    include_aria: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "limit",
            max(
                1,
                min(
                    100,
                    int(self.limit),
                ),
            ),
        )

        object.__setattr__(
            self,
            "min_quality",
            max(
                0.0,
                min(
                    1.0,
                    float(self.min_quality),
                ),
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class KnowledgeArchitecture:
    """
    Registry and validation layer for ARIA's durable knowledge foundation.

    This class does not fetch, write or delete knowledge. It only defines
    the architecture and validates records/sources so Steps 8 and 9 have a
    stable contract.
    """

    VERSION = "PHASE1-KNOWLEDGE-ARCH-20261004"

    DEFAULT_SOURCE_DEFINITIONS = (
        KnowledgeSource(
            source_id="wikipedia",
            name="Wikipedia",
            source_type="encyclopedia",
            authority=0.88,
            freshness=KnowledgeFreshness.PERIODIC,
            domains=(
                "general",
                "science",
                "engineering",
                "computer_science",
            ),
            ingestion_policy="scheduled",
        ),
        KnowledgeSource(
            source_id="wikidata",
            name="Wikidata",
            source_type="knowledge_graph",
            authority=0.90,
            freshness=KnowledgeFreshness.PERIODIC,
            domains=(
                "general",
                "science",
                "engineering",
            ),
            ingestion_policy="scheduled",
        ),
        KnowledgeSource(
            source_id="programming_docs",
            name="Programming Documentation",
            source_type="documentation",
            authority=0.95,
            freshness=KnowledgeFreshness.PERIODIC,
            domains=(
                "programming",
                "computer_science",
                "engineering",
            ),
            ingestion_policy="version_aware",
        ),
        KnowledgeSource(
            source_id="science_math",
            name="Science and Mathematics References",
            source_type="reference",
            authority=0.93,
            freshness=KnowledgeFreshness.DURABLE,
            domains=(
                "science",
                "mathematics",
                "engineering",
            ),
            ingestion_policy="curated",
        ),
        KnowledgeSource(
            source_id="ai_ml",
            name="AI and Machine Learning References",
            source_type="documentation_and_papers",
            authority=0.93,
            freshness=KnowledgeFreshness.PERIODIC,
            domains=(
                "artificial_intelligence",
                "computer_science",
            ),
            ingestion_policy="curated_and_scheduled",
        ),
        KnowledgeSource(
            source_id="aria_internal",
            name="ARIA Internal Knowledge",
            source_type="project_documentation",
            authority=0.98,
            freshness=KnowledgeFreshness.DURABLE,
            domains=(
                "aria",
                "programming",
                "computer_science",
            ),
            ingestion_policy="development_event",
        ),
    )

    def __init__(
        self,
        sources: Iterable[KnowledgeSource] | None = None,
    ) -> None:

        self._sources: dict[
            str,
            KnowledgeSource,
        ] = {}

        for source in (
            sources
            or self.DEFAULT_SOURCE_DEFINITIONS
        ):
            self.register_source(source)

    @property
    def sources(
        self,
    ) -> tuple[KnowledgeSource, ...]:
        return tuple(
            self._sources.values()
        )

    def register_source(
        self,
        source: KnowledgeSource,
    ) -> KnowledgeSource:

        if not isinstance(
            source,
            KnowledgeSource,
        ):
            raise TypeError(
                "source must be KnowledgeSource"
            )

        source_id = source.source_id.strip()

        if not source_id:
            raise ValueError(
                "source_id cannot be empty"
            )

        if source_id in self._sources:
            raise ValueError(
                f"Knowledge source already registered: {source_id}"
            )

        self._sources[source_id] = source

        return source

    def get_source(
        self,
        source_id: str,
    ) -> KnowledgeSource | None:

        return self._sources.get(
            str(source_id).strip()
        )

    def validate_record(
        self,
        record: KnowledgeRecord,
    ) -> tuple[str, ...]:
        """Validate structural invariants without contacting any provider."""

        errors: list[str] = []

        if not record.knowledge_id.strip():
            errors.append(
                "knowledge_id is empty"
            )

        if not record.title.strip():
            errors.append(
                "title is empty"
            )

        if not record.content.strip():
            errors.append(
                "content is empty"
            )

        if not record.provenance:
            errors.append(
                "at least one provenance entry is required"
            )

        for provenance in record.provenance:

            if not provenance.source_id.strip():
                errors.append(
                    "provenance source_id is empty"
                )

            elif (
                provenance.source_id
                not in self._sources
            ):
                errors.append(
                    "unknown provenance source: "
                    f"{provenance.source_id}"
                )

        if (
            record.chunk_index is not None
            and record.chunk_index < 0
        ):
            errors.append(
                "chunk_index cannot be negative"
            )

        return tuple(errors)

    def is_valid_record(
        self,
        record: KnowledgeRecord,
    ) -> bool:

        return not self.validate_record(
            record
        )

    def classify_source(
        self,
        source_id: str,
    ) -> dict[str, Any]:

        source = self.get_source(
            source_id
        )

        if source is None:
            return {
                "source_id": source_id,
                "known": False,
            }

        return {
            "source_id": source.source_id,
            "known": True,
            "name": source.name,
            "source_type": source.source_type,
            "authority": source.authority,
            "freshness": source.freshness.value,
            "domains": list(source.domains),
            "enabled": source.enabled,
            "ingestion_policy": source.ingestion_policy,
        }

    def describe(self) -> dict[str, Any]:
        """Return a machine-readable architecture contract."""

        return {
            "version": self.VERSION,
            "purpose": (
                "durable provider-independent "
                "knowledge foundation"
            ),
            "separation": {
                "personal_memory": (
                    "user-specific episodic/semantic memory"
                ),
                "knowledge": (
                    "general and project knowledge"
                ),
                "current_information": (
                    "live/web/tool retrieval at query time"
                ),
            },
            "domains": [
                item.value
                for item in KnowledgeDomain
            ],
            "kinds": [
                item.value
                for item in KnowledgeKind
            ],
            "freshness": [
                item.value
                for item in KnowledgeFreshness
            ],
            "verification": [
                item.value
                for item in VerificationStatus
            ],
            "sources": [
                source.to_dict()
                for source in self.sources
            ],
            "contracts": {
                "record": "KnowledgeRecord",
                "query": "KnowledgeQuery",
                "source": "KnowledgeSource",
                "provenance": "Provenance",
                "quality": "KnowledgeQuality",
            },
            "storage_layers": [
                "canonical_records",
                "text_index",
                "vector_index",
                "knowledge_graph",
            ],
            "future_steps": {
                "8": "knowledge ingestion",
                "9": "knowledge retrieval",
            },
        }


__all__ = [
    "KnowledgeArchitecture",
    "KnowledgeDomain",
    "KnowledgeFreshness",
    "KnowledgeKind",
    "KnowledgeQuality",
    "KnowledgeQuery",
    "KnowledgeRecord",
    "KnowledgeSource",
    "Provenance",
    "VerificationStatus",
]