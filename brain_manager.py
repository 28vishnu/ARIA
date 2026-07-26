import os
import chromadb
from datetime import datetime, timezone, timedelta

class AriaBrain:
    def __init__(self, chroma_client=None):
        self.client = chroma_client if chroma_client else chromadb.PersistentClient(path="./aria_vectors")
        # Specialized collections based on the ARIA OS blueprint
        self.knowledge_col = self.client.get_or_create_collection(name="brain_knowledge")
        self.skills_col = self.client.get_or_create_collection(name="brain_skills")
        self.code_col = self.client.get_or_create_collection(name="brain_code")

    def search_brain(self, query: str, embedding_fn, topic: str = None) -> dict | None:
        """Searches the persistent knowledge brain semantically with usage count updates."""
        try:
            emb = embedding_fn(query)
            
            # Optional topic filtering
            where_filter = {"topic": topic} if topic else None

            results = self.knowledge_col.query(
                query_embeddings=[emb],
                n_results=1,
                where=where_filter,
                include=["documents", "metadatas", "distances"]
            )
            
            if results and results.get("documents") and results["documents"][0]:
                distance = results["distances"][0][0]
                if distance < 0.35: # High-confidence match threshold
                    meta = results["metadatas"][0][0]
                    doc_id = results["ids"][0][0]
                    answer = results["documents"][0][0]
                    
                    # Check freshness / expiration
                    expires_at = meta.get("expires_at")
                    if expires_at:
                        exp_dt = datetime.fromisoformat(expires_at)
                        if datetime.now(timezone.utc) > exp_dt:
                            return None # Stale entry

                    # Dynamically update usage count and last_used timestamp in ChromaDB
                    new_uses = meta.get("uses", 0) + 1
                    meta["uses"] = new_uses
                    meta["last_used"] = datetime.now(timezone.utc).isoformat()
                    
                    try:
                        self.knowledge_col.update(
                            ids=[doc_id],
                            metadatas=[meta]
                        )
                    except Exception:
                        pass # Non-blocking metadata update

                    return {
                        "answer": answer,
                        "confidence": meta.get("confidence", 0.9),
                        "verified": meta.get("verified", False),
                        "uses": new_uses,
                        "id": doc_id
                    }
        except Exception as e:
            print(f"[Brain Search Error]: {e}")
        return None

    def store_knowledge(self, question: str, answer: str, topic: str, category: str, reasoning_summary: str, source: str, confidence: float, verified: bool, embedding_fn, expires_in_days: int = None):
        """Stores structured knowledge with combined Q&A document framing for better embeddings."""
        try:
            doc_id = f"brain_{datetime.now().timestamp()}"
            
            # Combined text gives the embedding model superior context
            combined_document = f"""
Topic: {topic}
Category: {category}
Question: {question}
Reasoning: {reasoning_summary}
Answer: {answer}
            """.strip()

            emb = embedding_fn(combined_document)
            
            expires_at = None
            if expires_in_days:
                expires_at = (datetime.now(timezone.utc) + timedelta(days=expires_in_days)).isoformat()

            metadata = {
                "topic": topic.lower(),
                "category": category.lower(),
                "question": question,
                "source": source,
                "confidence": confidence,
                "verified": verified,
                "uses": 1,
                "created": datetime.now(timezone.utc).isoformat(),
                "last_used": datetime.now(timezone.utc).isoformat(),
                "expires_at": expires_at or ""
            }

            self.knowledge_col.add(
                ids=[doc_id],
                documents=[combined_document],
                embeddings=[emb],
                metadatas=[metadata]
            )
            print(f"[Learning Engine]: Indexed new knowledge under topic '{topic}' (Confidence: {confidence})")
        except Exception as e:
            print(f"[Brain Store Error]: {e}")
