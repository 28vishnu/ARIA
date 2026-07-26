from brain.document_index import DocumentIndex
from brain.graph import GraphManager
from brain.cache import CacheManager
from brain.retrieval import RetrievalEngine

class AriaBrain:
    def __init__(self, chroma_client, mongo_db, memory_engine = None):
        self.documents = DocumentIndex(chroma_client, mongo_db)
        self.graph = GraphManager(mongo_db)
        self.cache = CacheManager(chroma_client)
        self.memory = memory_engine
        self.retrieval = RetrievalEngine(self.documents, self.memory, self.graph, self.cache)

    async def search(self, query: str) -> dict:
        """Single unified entry point for all information retrieval across ARIA OS."""
        return await self.retrieval.unified_search(query)

    async def register_document(self, doc_id: str, filename: str, raw_text: str):
        """Delegates file registration to the persistent document index."""
        return await self.documents.register_document(doc_id, filename, raw_text)

    async def link_concepts(self, entity_a: str, relation: str, entity_b: str, category: str = "general"):
        """Delegates graph linking to persistent MongoDB graph manager."""
        await self.graph.link_concepts(entity_a, relation, entity_b, category)

    def search_brain(self, question: str):
        """Legacy compatibility wrapper for existing callers."""
        cached = self.cache.search_cache(question)
        if cached:
            return {"confidence": 0.96, "answer": cached}
        return None

    def store_knowledge(self, question: str, answer: str, **kwargs):
        """Stores verified knowledge into the cache."""
        self.cache.store_cache(question, answer)
