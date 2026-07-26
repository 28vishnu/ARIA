from datetime import datetime, timezone

class CacheManager:
    def __init__(self, chroma_repo):
        self.chroma = chroma_repo

    def get(self, query: str):
        if not self.chroma.cache: return None
        hits = self.chroma.cache.query(query_texts=[query], n_results=1)
        if hits and hits.get("documents") and hits.get("distances") and len(hits["distances"][0]) > 0:
            if hits["distances"][0][0] < 0.35:
                return hits["documents"][0][0]
        return None

    def set(self, query: str, answer: str):
        if self.chroma.cache:
            self.chroma.cache.upsert(ids=[str(datetime.now(timezone.utc).timestamp())], documents=[answer], metadatas=[{"question": query}])
