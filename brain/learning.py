from datetime import datetime, timezone
from .freshness import calculate_expiration

def store_or_update_knowledge(collection, question: str, answer: str, topic: str, category: str, summary: str, source: str, confidence: float, verified: bool, knowledge_type: str, embedding_fn):
    try:
        emb = embedding_fn(question)
        if all(v == 0.0 for v in emb): return

        existing = collection.query(query_embeddings=[emb], n_results=1, include=["metadatas", "distances", "ids"])
        if existing and existing.get("distances") and existing["distances"][0] and existing["distances"][0][0] < 0.20:
            doc_id = existing["ids"][0][0]
            meta = existing["metadatas"][0][0]
            meta["answer"] = answer
            meta["summary"] = summary
            meta["confidence"] = max(meta.get("confidence", 0.9), confidence)
            meta["last_used"] = datetime.now(timezone.utc).isoformat()
            meta["uses"] = meta.get("uses", 0) + 1
            
            combined_doc = f"Topic: {topic} | Category: {category} | Question: {meta.get('question')} | Summary: {summary}"
            collection.update(ids=[doc_id], embeddings=[embedding_fn(combined_doc)], metadatas=[meta])
            return

        doc_id = f"brain_{datetime.now().timestamp()}"
        combined_doc = f"Topic: {topic}\nCategory: {category}\nQuestion: {question}\nSummary: {summary}"
        
        metadata = {
            "topic": topic.lower(), "category": category.lower(), "question": question,
            "answer": answer, "summary": summary, "knowledge_type": knowledge_type.upper(),
            "source": source, "confidence": confidence, "verified": verified, "uses": 1,
            "created": datetime.now(timezone.utc).isoformat(), "last_used": datetime.now(timezone.utc).isoformat(),
            "expires_at": calculate_expiration(knowledge_type) or ""
        }
        collection.add(ids=[doc_id], documents=[combined_doc], embeddings=[embedding_fn(combined_doc)], metadatas=[metadata])
    except Exception as e:
        print(f"[Learning Error]: {e}")
