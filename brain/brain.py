import chromadb
from .embeddings import get_embedding
from .search import search_knowledge_base
from .learning import store_or_update_knowledge
from .confidence import adjust_confidence

class AriaBrain:
    def __init__(self, chroma_client=None):
        self.client = chroma_client if chroma_client else chromadb.PersistentClient(path="./aria_vectors")
        self.knowledge_col = self.client.get_or_create_collection(name="brain_knowledge")
        self.skills_col = self.client.get_or_create_collection(name="brain_skills")
        self.code_col = self.client.get_or_create_collection(name="brain_code")

    def search_brain(self, query: str, topic: str = None) -> dict | None:
        return search_knowledge_base(self.knowledge_col, query, get_embedding, topic)

    def store_knowledge(self, question: str, answer: str, topic: str = "general", category: str = "general", summary: str = "", source: str = "AI", confidence: float = 0.95, verified: bool = False, knowledge_type: str = "STATIC"):
        store_or_update_knowledge(self.knowledge_col, question, answer, topic, category, summary, source, confidence, verified, knowledge_type, get_embedding)

    def update_feedback(self, doc_id: str, feedback: str):
        """Updates confidence based on user feedback."""
        try:
            res = self.knowledge_col.get(ids=[doc_id], include=["metadatas"])
            if res and res.get("metadatas") and res["metadatas"][0]:
                meta = res["metadatas"][0]
                meta["confidence"] = adjust_confidence(meta.get("confidence", 0.9), feedback)
                self.knowledge_col.update(ids=[doc_id], metadatas=[meta])
        except Exception as e:
            print(f"[Feedback Error]: {e}")
