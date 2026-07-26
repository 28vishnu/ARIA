import os
import chromadb
from datetime import datetime, timezone, timedelta

class AriaBrain:
    def __init__(self, chroma_client=None):
        self.client = chroma_client if chroma_client else chromadb.PersistentClient(path="./aria_vectors")
        self.knowledge_col = self.client.get_or_create_collection(name="brain_knowledge")

    def search_brain(self, query: str, embedding_fn) -> dict | None:
        """Searches the persistent knowledge brain semantically."""
        try:
            emb = embedding_fn(query)
            results = self.knowledge_col.query(
                query_embeddings=[emb],
                n_results=1,
                include=["documents", "metadatas", "distances"]
            )
            
            if results and results.get("documents") and results["documents"][0]:
                distance = results["distances"][0][0]
                # ChromaDB cosine/l2 distance threshold for high-confidence match
                if distance < 0.35: 
                    meta = results["metadatas"][0][0]
                    answer = results["documents"][0][0]
                    
                    # Check freshness / expiration
                    expires_at = meta.get("expires_at")
                    if expires_at:
                        exp_dt = datetime.fromisoformat(expires_at)
                        if datetime.now(timezone.utc) > exp_dt:
                            return None # Stale entry

                    return {
                        "answer": answer,
                        "confidence": meta.get("confidence", 0.9),
                        "uses": meta.get("uses", 0) + 1,
                        "id": results["ids"][0][0]
                    }
        except Exception as e:
            print(f"[Brain Search Error]: {e}")
        return None

    def store_knowledge(self, question: str, answer: str, source: str, confidence: float, embedding_fn, expires_in_days: int = None):
        """Permanently stores a new fact, code snippet, or skill into the brain."""
        try:
            doc_id = f"brain_{datetime.now().timestamp()}"
            emb = embedding_fn(question)
            
            expires_at = None
            if expires_in_days:
                expires_at = (datetime.now(timezone.utc) + timedelta(days=expires_in_days)).isoformat()

            metadata = {
                "question": question,
                "source": source,
                "confidence": confidence,
                "uses": 1,
                "created": datetime.now(timezone.utc).isoformat(),
                "expires_at": expires_at or ""
            }

            self.knowledge_col.add(
                ids=[doc_id],
                documents=[answer],
                embeddings=[emb],
                metadatas=[metadata]
            )
            print(f"[Brain Learning Engine]: Successfully indexed new knowledge for query: '{question[:30]}...'")
        except Exception as e:
            print(f"[Brain Store Error]: {e}")
