from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import uuid


@dataclass
class Document:

    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    name: str = ""

    path: str = ""

    extension: str = ""

    size: int = 0

    created_at: datetime = field(default_factory=datetime.utcnow)

    indexed: bool = False

    summary: str = ""

    metadata: dict = field(default_factory=dict)

    concepts: list[str] = field(default_factory=list)

    pages: list = field(default_factory=list)


@dataclass
class DocumentPage:

    number: int

    text: str = ""

    images: list = field(default_factory=list)

    tables: list = field(default_factory=list)

    metadata: dict = field(default_factory=dict)


@dataclass
class DocumentChunk:

    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    document_id: str = ""

    page: int = 0

    text: str = ""

    embedding: list[float] | None = None

    metadata: dict = field(default_factory=dict)


@dataclass
class DocumentConcept:

    name: str

    description: str = ""

    importance: float = 0.0

    pages: list[int] = field(default_factory=list)
