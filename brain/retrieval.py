import asyncio
from brain.models.request import BrainRequest

class RetrievalEngine:
    def __init__(self, chroma_repo, mongo_repo, cache_mgr):
        self.chroma = chroma_repo
        self.mongo = mongo_repo
        self.cache = cache_mgr

    async def parallel_search(self, request: BrainRequest) -> dict:
        """Executes independent retrieval tasks (Cache, Profile, Memory, Graph) concurrently using asyncio.gather()."""
        query_lower = request.query.lower()

        # 1. Fast Cache Check First (< 15ms)
        cached_ans = self.cache.get(request.query)
        if cached_ans:
            return {"source": "cache", "content": cached_ans}

        # 2. Define concurrent asynchronous fetchers
        async def fetch_profile():
            if self.mongo.profile is not None:
                return await self.mongo.profile.find_one({"_id": "master_profile"}) or {}
            return {}

        async def fetch_documents():
            if self.chroma.docs is not None:
                res = self.chroma.docs.query(query_texts=[request.query], n_results=3)
                if res and res.get("metadatas") and len(res["metadatas"][0]) > 0:
                    return res["metadatas"][0]
            return []

        async def fetch_graph_edges():
            if self.mongo.graph is not None:
                # Find matching entity edges
                doc = await self.mongo.graph.find_one({"entity": {"$regex": request.query, "$options": "i"}})
                return doc.get("edges", []) if doc else []
            return []

        # 3. Fire independent operations concurrently
        profile_task = asyncio.create_task(fetch_profile())
        docs_task = asyncio.create_task(fetch_documents())
        graph_task = asyncio.create_task(fetch_graph_edges())

        profile_data, doc_results, graph_edges = await asyncio.gather(
            profile_task, docs_task, graph_task
        )

        return {
            "source": "retrieval",
            "profile": profile_data,
            "documents": doc_results,
            "graph": graph_edges,
            "has_results": bool(doc_results or graph_edges or profile_data)
        }
