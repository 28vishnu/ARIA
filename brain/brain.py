from brain.models.request import BrainRequest
from brain.events import EventBus
from brain.repositories.mongo import MongoRepository
from brain.repositories.chroma import ChromaRepository
from brain.document_index import DocumentIndex
from brain.graph import GraphManager
from brain.cache import CacheManager
from brain.retrieval import RetrievalEngine
from brain.knowledge.learning_engine import LearningEngine

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
        self.learning = LearningEngine(mongo_db)

    def classify_request(self, request):
        """
        Placeholder for future routing optimizations.
        """
        return "general"

    def should_use_reasoning(self, route):
        return route in (
            "planner",
            "general",
            "tool",
        )

    async def search(self, request: BrainRequest) -> dict:
        """Deterministic Kernel Orchestrator with Confidence Scoring and Correction Matching."""
        query = request.query
        lower_q = query.lower()

        # 1. Check Learning Engine for Past Corrections (100% Confidence)
        correction = await self.learning.check_correction(query)
        if correction:
            return {
                "source": "learning_engine",
                "content": correction,
                "confidence": 1.0
            }

        # 2. Check Profile Data (100% Confidence)
        if any(k in lower_q for k in ["my name", "who am i", "my profile", "college", "course"]):
            profile = {}
            if self.mongo.profile is not None:
                profile = await self.mongo.profile.find_one({"_id": "master_profile"}) or {}
            if profile:
                return {
                    "source": "profile",
                    "profile": profile,
                    "confidence": 1.0,
                    "has_results": True
                }

        # 3. Parallel Retrieval across Memory, Documents, & Graph
        retrieval_res = await self.retrieval.parallel_search(request)
        
        # Determine confidence score based on hit quality
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
        await self.learning.record_correction(query, wrong_ans, correction)

    async def plan(self, goal):
        planner = self.registry.get("planner_engine")
        executor = self.registry.get("plan_executor")
        verifier = self.registry.get("plan_verifier")

        plan = await planner.create_plan(goal)
        plan = await executor.execute(plan)
        verified = await verifier.verify(plan)

        return {
            "verified": verified,
            "plan": plan,
        }

brain/brain.py
