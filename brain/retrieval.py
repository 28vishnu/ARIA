import asyncio
import time
import re
from datetime import datetime, timezone
from brain.models.request import BrainRequest

class RetrievalEngine:
    def __init__(self, chroma_repo, mongo_repo, cache_mgr):
        self.chroma = chroma_repo
        self.mongo = mongo_repo
        self.cache = cache_mgr

    def _normalize_query(self, query: str) -> str:
        """Normalizes query text (lowercase, collapse whitespace, strip punctuation) to maximize cache hits."""
        cleaned = query.lower().strip()
        cleaned = re.sub(r'[^\w\s]', '', cleaned)  # Strip punctuation
        cleaned = re.sub(r'\s+', ' ', cleaned)      # Collapse spaces
        return cleaned

    async def parallel_search(self, request: BrainRequest) -> dict:
        """Executes intent-aware, non-blocking parallel retrieval with partial failure handling, cleanup, and metrics."""
        start_time = time.perf_counter()
        timings = {}

        raw_query = request.query
        norm_query = self._normalize_query(raw_query)
        intent = request.intent

        # 1. Check Retrieval Cache First
        cache_start = time.perf_counter()
        cache_key = f"retrieval:{intent}:{norm_query}"
        cached_res = self.cache.get(cache_key)
        timings["cache_ms"] = round((time.perf_counter() - cache_start) * 1000, 2)

        if cached_res:
            cached_res["timings"] = timings
            return cached_res

        # 2. Define non-blocking fetchers with individual source timing
        async def fetch_profile():
            t0 = time.perf_counter()
            try:
                if intent in ["general", "profile"] and self.mongo.profile is not None:
                    res = await self.mongo.profile.find_one({"_id": "master_profile"})
                    timings["profile_ms"] = round((time.perf_counter() - t0) * 1000, 2)
                    return res or {}
            except Exception as e:
                print(f"[Retrieval Profile Error]: {e}")
            timings["profile_ms"] = round((time.perf_counter() - t0) * 1000, 2)
            return {}

        async def fetch_documents():
            t0 = time.perf_counter()
            try:
                if intent in ["general", "document_search", "media_search"] and self.chroma.docs is not None:
                    def _chroma_query():
                        return self.chroma.docs.query(query_texts=[raw_query], n_results=3)
                    res = await asyncio.to_thread(_chroma_query)
                    timings["documents_ms"] = round((time.perf_counter() - t0) * 1000, 2)
                    if res and res.get("metadatas") and len(res["metadatas"][0]) > 0:
                        return res["metadatas"][0]
            except Exception as e:
                print(f"[Retrieval Chroma Error]: {e}")
            timings["documents_ms"] = round((time.perf_counter() - t0) * 1000, 2)
            return []

        async def fetch_graph_edges():
            t0 = time.perf_counter()
            try:
                if intent in ["general", "graph"] and self.mongo.graph is not None:
                    # Optimized exact or indexed search, falling back cleanly
                    doc = await self.mongo.graph.find_one({"entity": norm_query})
                    if not doc:
                        doc = await self.mongo.graph.find_one({"entity": {"$regex": raw_query, "$options": "i"}})
                    timings["graph_ms"] = round((time.perf_counter() - t0) * 1000, 2)
                    return doc.get("edges", []) if doc else []
            except Exception as e:
                print(f"[Retrieval Graph Error]: {e}")
            timings["graph_ms"] = round((time.perf_counter() - t0) * 1000, 2)
            return []

        # 3. Assemble and execute tasks concurrently with return_exceptions=True
        tasks = [
            asyncio.create_task(fetch_profile()),
            asyncio.create_task(fetch_documents()),
            asyncio.create_task(fetch_graph_edges())
        ]

        profile_data, doc_results, graph_edges = {}, [], []
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True), timeout=2.0
            )
            
            # Process results individually to prevent partial failures from crashing gather
            profile_data = results[0] if not isinstance(results[0], Exception) else {}
            doc_results = results[1] if not isinstance(results[1], Exception) else []
            graph_edges = results[2] if not isinstance(results[2], Exception) else []

        except asyncio.TimeoutError:
            print("[Retrieval Warning]: Parallel retrieval timed out after 2.0s. Cleaning up orphaned tasks...")
            for task in tasks:
                if not task.done():
                    task.cancel()

        total_ms = round((time.perf_counter() - start_time) * 1000, 2)
        timings["total_ms"] = total_ms

        response_payload = {
            "source": "retrieval",
            "profile": profile_data,
            "documents": doc_results,
            "graph": graph_edges,
            "has_results": bool(doc_results or graph_edges or profile_data),
            "timings": timings
        }

        # 4. Cache normalized result for 5 minutes
        if response_payload["has_results"]:
            self.cache.set(cache_key, response_payload)

        return response_payload
