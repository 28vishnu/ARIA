from datetime import datetime, timezone
from .freshness import is_stale

def search_knowledge_base(collection, query: str, embedding_fn, topic: str = None) -> dict | None:
    try:
        emb = embedding_fn(query)
        # Skip search if fallback zero vector is returned due to API quota failure
        if all(v == 0.0 for v in emb):
            return None

        where_filter = {"topic": topic} if topic else None

        results = collection.query(
            query_embeddings=[emb],
            n_results=1,
            where=where_filter,
            include=["documents", "metadatas", "distances"]
        )
        
        if results and results.get("metadatas") and results["metadatas"][0]:
            distance = results["distances"][0][0]
            if distance < 0.35: 
                meta = results["metadatas"][0][0]
                doc_id = results["ids"][0][0]
                
                if is_stale(meta.get("expires_at")):
                    return None 

                new_uses = meta.get("uses", 0) + 1
                meta["uses"] = new_uses
                meta["last_used"] = datetime.now(timezone.utc).isoformat()
                
                try:
                    collection.update(ids=[doc_id], metadatas=[meta])
                except Exception:
                    pass 

                return {
                    "answer": meta.get("answer", ""),
                    "confidence": meta.get("confidence", 0.9),
                    "verified": meta.get("verified", False),
                    "uses": new_uses,
                    "id": doc_id
                }
    except Exception as e:
        print(f"[Search Engine Error]: {e}")
    return None
