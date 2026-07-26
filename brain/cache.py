import os
from datetime import datetime, timezone
import chromadb

class CacheManager:
    def __init__(self, chroma_client):
        self.chroma = chroma_client
        self.cache_col = chroma_client.get_or_create_collection(name="aria_brain_cache")

    def search_cache(self, query: str) -> str | None:
        """Searches verified QA cache with semantic similarity."""
        try:
            hits = self.cache_col.query(query_texts=[query], n_results=1)
            if hits and hits.get("documents") and len(hits["documents"][0]) > 0:
                dist = hits.get("distances", [[1.0]])[0][0]
                if dist < 0.35:  # High confidence threshold
                    return hits["documents"][0][0]
        except Exception as e:
            print(f"[Cache Search Error]: {e}")
        return None

    def store_cache(self, question: str, answer: str, confidence: float = 0.96):
        """Stores verified Q&A into cache."""
        self.cache_col.upsert(
            ids=[str(datetime.now(timezone.utc).timestamp())],
            documents=[answer],
            metadatas=[{"question": question, "confidence": confidence}]
        )
