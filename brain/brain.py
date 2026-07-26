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

    async def search(self, request: BrainRequest) -> dict:
        """Kernel Orchestrator: Intent inspection and parallel context building."""
        lower_q = request.query.lower()

        # Intent Routing: Bypass heavy retrieval for targeted profile queries
        if any(k in lower_q for k in ["my name", "who am i", "my profile"]):
            profile = {}
            if self.mongo.profile is not None:
                profile = await self.mongo.profile.find_one({"_id": "master_profile"}) or {}
            return {"source": "profile", "profile": profile}

        # Intent Routing: Standard parallel retrieval across stores
        return await self.retrieval.parallel_search(request)

    async def recall(self, request: BrainRequest) -> dict:
        return await self.search(request)

    async def learn(self, request: BrainRequest, filename: str, text: str):
        """Cognitive Mode: Ingest and learn new artifacts."""
        return await self.documents.index_document(request, filename, text)

    async def reason(self, request: BrainRequest) -> str:
        res = await self.search(request)
        return str(res)

    def store_knowledge(self, question: str, answer: str):
        self.cache.set(question, answer)
