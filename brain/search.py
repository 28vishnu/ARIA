from datetime import datetime, timezone
from .freshness import is_stale

def search_knowledge_base(collection, query: str, embedding_fn, topic: str = None) -> dict | None:
    try:
        emb = embedding_fn(query)
        if all(v == 0.0 for v in emb): return None

        results = collection.query(query_embeddings=[emb], n_results=1, where={"topic": topic} if topic else None, include=["documents", "metadatas", "distances"])
        if results and results.get("metadatas") and results["metadatas"][0]:
            if results["distances"][0][0] < 0.35:
                meta = results["metadatas"][0][0]
                doc_id = results["ids"][0][0]
                if is_stale(meta.get("expires_at")): return None

                meta["uses"] = meta.get("uses", 0) + 1
                meta["last_used"] = datetime.now(timezone.utc).isoformat()
                try: collection.update(ids=[doc_id], metadatas=[meta])
                except Exception: pass

                return {"answer": meta.get("answer", ""), "confidence": meta.get("confidence", 0.9), "verified": meta.get("verified", False), "uses": meta["uses"], "id": doc_id}
    except Exception as e:
        print(f"[Search Error]: {e}")
    return None
