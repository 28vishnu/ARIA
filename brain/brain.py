from brain.models.request import BrainRequest
from brain.events import EventBus
from brain.repositories.mongo import MongoRepository
from brain.repositories.chroma import ChromaRepository
from brain.document_index import DocumentIndex
from brain.graph import GraphManager
from brain.cache import CacheManager
from brain.retrieval import RetrievalEngine

class AriaBrain:
    def __init__(self, chroma_client, mongo_db):
        self.events = EventBus()
        self.mongo = MongoRepository(mongo_db)
        self.chroma = ChromaRepository(chroma_client)
        
        self.cache = CacheManager(self.chroma)
        self.graph = GraphManager(self.mongo)
        self.documents = DocumentIndex(self.chroma, self.mongo, self.events)
        self.retrieval = RetrievalEngine(self.chroma, self.mongo, self.cache)

    async def recall(self, request: BrainRequest) -> dict:
        """Cognitive Mode: Recall memories or profile data."""
        return await self.retrieval.search(request)

    async def search(self, request: BrainRequest) -> dict:
        """Cognitive Mode: Unified search across all stores."""
        return await self.retrieval.search(request)

    async def learn(self, request: BrainRequest, filename: str, text: str):
        """Cognitive Mode: Ingest and learn new artifacts."""
        return await self.documents.index_document(request, filename, text)

    async def reason(self, request: BrainRequest) -> str:
        """Cognitive Mode: Synthesize answers."""
        res = await self.search(request)
        return str(res)
