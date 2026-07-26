class RetrievalEngine:
    def __init__(self, document_index, memory_engine, graph_manager, cache_manager):
        self.docs = document_index
        self.memory = memory_engine
        self.graph = graph_manager
        self.cache = cache_manager

    async def unified_search(self, query: str) -> dict:
        """Executes a multi-source parallel search across cache, documents, and memory, returning ranked results."""
        # 1. Check QA Cache First
        cached_ans = self.cache.search_cache(query)
        if cached_ans:
            return {"type": "cache", "content": cached_ans, "score": 0.99}

        # 2. Parallel retrieve from Documents and Memories
        doc_results = await self.docs.search(query)
        memory_results = await self.memory.get_relevant_memories(query) if self.memory else ""

        # 3. Compile and Rank
        ranked = {
            "documents": doc_results,
            "memories": memory_results,
            "has_results": bool(doc_results or memory_results)
        }
        return ranked
