from dataclasses import dataclass, field
from datetime import datetime
import uuid
import logging

logger = logging.getLogger("aria")


@dataclass
class KnowledgeMemory:

    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    document_id: str = ""

    document_name: str = ""

    concept: str = ""

    description: str = ""

    source_page: int = 0

    importance: float = 0.0

    created_at: datetime = field(default_factory=datetime.utcnow)

    metadata: dict = field(default_factory=dict)


class DocumentMemory:

    def __init__(self):

        self.memories = []

    def store_document(
        self,
        document,
        concepts,
    ):

        for concept in concepts:

            memory = KnowledgeMemory(

                document_id=document.id,

                document_name=document.name,

                concept=concept.name,

                description=concept.description,

                source_page=concept.pages[0]
                if concept.pages else 0,

                importance=concept.importance,

            )

            self.memories.append(memory)

        logger.info(
            "[DocumentMemory] Stored %d concepts from %s",
            len(concepts),
            document.name,
        )

    def search(
        self,
        query: str,
        limit: int = 5,
    ):

        query = query.lower()

        matches = []

        for memory in self.memories:

            if (
                query in memory.concept.lower()
                or query in memory.description.lower()
            ):
                matches.append(memory)

        matches.sort(
            key=lambda m: m.importance,
            reverse=True,
        )

        return matches[:limit]
