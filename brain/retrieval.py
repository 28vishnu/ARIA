import asyncio
from brain.models.request import BrainRequest

class RetrievalEngine:
    def __init__(self, chroma_repo, mongo_repo, cache_mgr):
        self.chroma = chroma_repo
        self.mongo = mongo_repo
        self.cache = cache_mgr

    async def parallel_search(self, request: BrainRequest) -> dict:
        """Executes intent-aware, non-blocking parallel retrieval across stores with timeout protection."""
        query_text = request.query
        intent = request.intent

        # 1. Check Retrieval Cache First (< 10ms)
        cache_key = f"retrieval:{intent}:{query_text.lower().strip()}"
        cached_res = self.cache.get(cache_key)
        if cached_res:
            return cached_res

        # 2. Define non-blocking fetchers
        async def fetch_profile():
            if intent in ["general", "profile"] and self.mongo.profile is not None:
                return await self.mongo.profile.find_one({"_id": "master_profile"}) or {}
            return {}

        async def fetch_documents():
            if intent in ["general", "document_search", "media_search"] and self.chroma.docs is not None:
                def _chroma_query():
                    return self.chroma.docs.query(query_texts=[query_text], n_results=3)
                try:
                    res = await asyncio.to_thread(_chroma_query)
                    if res and res.get("metadatas") and len(res["metadatas"][0]) > 0:
                        return res["metadatas"][0]
                except Exception as e:
                    print(f"[Retrieval Chroma Warning]: {e}")
            return []

        async def fetch_graph_edges():
            if intent in ["general", "graph"] and self.mongo.graph is not None:
                doc = await self.mongo.graph.find_one({"entity": {"$regex": query_text, "$options": "i"}})
                return doc.get("edges", []) if doc else []
            return []

        # 3. Assemble and execute tasks concurrently with a strict 2-second timeout
        tasks = [
            asyncio.create_task(fetch_profile()),
            asyncio.create_task(fetch_documents()),
            asyncio.create_task(fetch_graph_edges())
        ]

        try:
            profile_data, doc_results, graph_edges = await asyncio.wait_for(
                asyncio.gather(*tasks), timeout=2.0
            )
        except asyncio.TimeoutError:
            print("[Retrieval Warning]: Parallel retrieval timed out, returning partial results.")
            profile_data, doc_results, graph_edges = {}, [], []

        result = {
            "source": "retrieval",
            "profile": profile_data,
            "documents": doc_results,
            "graph": graph_edges,
            "has_results": bool(doc_results or graph_edges or profile_data)
        }

        # 4. Cache retrieval results for 5 minutes (TTL / Cache set)
        if result["has_results"]:
            self.cache.set(cache_key, result)

        return result
