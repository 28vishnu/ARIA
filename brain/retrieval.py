class RetrievalEngine:
    def __init__(self, chroma_repo, mongo_repo, cache_mgr):
        self.chroma = chroma_repo
        self.mongo = mongo_repo
        self.cache = cache_mgr

    async def search(self, request):
        cached = self.cache.get(request.query)
        if cached:
            return {"source": "cache", "content": cached}

        docs = []
        if self.chroma.docs:
            res = self.chroma.docs.query(query_texts=[request.query], n_results=3)
            if res and res.get("metadatas") and len(res["metadatas"][0]) > 0:
                docs = res["metadatas"][0]

        return {"source": "retrieval", "documents": docs}
