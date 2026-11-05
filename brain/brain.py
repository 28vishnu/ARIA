"""Compatibility facade for ARIA's retrieval kernel.

This facade intentionally uses a small correction store rather than the larger
LearningEngine, whose API is for source-backed knowledge ingestion and does not
provide correction lookup methods.
"""
import inspect

from brain.models.request import BrainRequest
from brain.events import EventBus
from brain.repositories.mongo import MongoRepository
from brain.repositories.chroma import ChromaRepository
from brain.document_index import DocumentIndex
from brain.graph import GraphManager
from brain.cache import CacheManager
from brain.retrieval import RetrievalEngine


class CorrectionStore:
    """Persist exact-query corrections in a dedicated Mongo collection."""

    def __init__(self, mongo_db):
        self.collection = (
            mongo_db["learning_corrections"] if mongo_db is not None else None
        )

    @staticmethod
    def _key(query):
        return " ".join(str(query or "").casefold().split())

    async def check_correction(self, query):
        if self.collection is None:
            return None
        key = self._key(query)
        if not key:
            return None
        pending = self.collection.find_one({"query_key": key})
        record = await pending if inspect.isawaitable(pending) else pending
        if not record:
            return None
        return record.get("correction")

    async def record_correction(self, query, wrong_ans, correction):
        if self.collection is None:
            return {"success": False, "reason": "correction store offline"}
        key = self._key(query)
        correction_text = str(correction or "").strip()
        if not key or not correction_text:
            return {"success": False, "reason": "query and correction are required"}
        pending = self.collection.update_one(
            {"query_key": key},
            {"$set": {
                "query_key": key,
                "query": str(query).strip(),
                "wrong_answer": str(wrong_ans or "").strip(),
                "correction": correction_text,
            }},
            upsert=True,
        )
        if inspect.isawaitable(pending):
            await pending
        return {"success": True}


class AriaBrain:
    def __init__(self, chroma_client, mongo_db, registry=None):
        self.events = EventBus()
        self.mongo = MongoRepository(mongo_db)
        self.chroma = ChromaRepository(chroma_client)
        self.registry = registry

        self.cache = CacheManager(self.chroma)
        self.graph = GraphManager(self.mongo)
        self.documents = DocumentIndex(self.chroma, self.mongo, self.events)
        self.retrieval = RetrievalEngine(self.chroma, self.mongo, self.cache)
        self.learning = CorrectionStore(mongo_db)

    def classify_request(self, request):
        return "general"

    def should_use_reasoning(self, route):
        return route in ("planner", "general", "tool")

    async def search(self, request: BrainRequest) -> dict:
        query = request.query
        lower_q = query.lower()

        correction = await self.learning.check_correction(query)
        if correction:
            return {"source": "learning_engine", "content": correction, "confidence": 1.0}

        if any(k in lower_q for k in ["my name", "who am i", "my profile", "college", "course"]):
            profile = {}
            if self.mongo.profile is not None:
                profile = await self.mongo.profile.find_one({"_id": "master_profile"}) or {}
            if profile:
                return {"source": "profile", "profile": profile, "confidence": 1.0, "has_results": True}

        retrieval_res = await self.retrieval.parallel_search(request)
        if retrieval_res.get("documents"):
            retrieval_res["confidence"] = 0.95
        elif retrieval_res.get("graph"):
            retrieval_res["confidence"] = 0.90
        else:
            retrieval_res["confidence"] = 0.0
        return retrieval_res

    async def learn(self, request: BrainRequest, filename: str, text: str):
        return await self.documents.index_document(request, filename, text)

    async def record_feedback(self, query: str, wrong_ans: str, correction: str):
        return await self.learning.record_correction(query, wrong_ans, correction)

    async def plan(self, goal):
        if self.registry is None:
            raise RuntimeError("Planning requires a configured service registry")
        planner = self.registry.get("planner_engine")
        plan = await planner.create_plan(goal)
        graph = await self.registry.get("graph_executor").execute(plan["graph"])
        verified = await self.registry.get("graph_verifier").verify(graph)
        return {"plan": plan["plan"], "graph": graph, "verified": verified}
