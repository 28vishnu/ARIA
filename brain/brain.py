import os
import chromadb
from datetime import datetime, timezone

class AriaBrain:
    def __init__(self, chroma_client):
        self.chroma = chroma_client
        # Dedicated collections for the unified intelligence engine
        self.brain_col = self.chroma.get_or_create_collection(name="aria_brain_cache")
        self.doc_meta_col = self.chroma.get_or_create_collection(name="aria_document_metadata")
        self.graph_edges = {}  # In-memory adjacency representation for the knowledge graph

    def link_concepts(self, entity_a: str, relation: str, entity_b: str, category: str = "general"):
        """Idempotently links concepts in the internal knowledge graph."""
        key = entity_a.lower().strip()
        if key not in self.graph_edges:
            self.graph_edges[key] = []
        edge = {"relation": relation, "target": entity_b.lower().strip(), "category": category}
        if edge not in self.graph_edges[key]:
            self.graph_edges[key].append(edge)

    def register_document(self, doc_id: str, filename: str, title: str, summary: str, keywords: list[str], aliases: list[str]):
        """Registers rich document metadata and aliases into the Brain index for smart synonym matching."""
        searchable_text = f"Title: {title}. Summary: {summary}. Filename: {filename}. Aliases: {', '.join(aliases)}. Keywords: {', '.join(keywords)}"
        self.doc_meta_col.upsert(
            ids=[doc_id],
            documents=[searchable_text],
            metadatas=[{
                "doc_id": doc_id,
                "filename": filename,
                "title": title,
                "summary": summary,
                "aliases": json_dumps_safe(aliases),
                "keywords": json_dumps_safe(keywords)
            }]
        )
        print(f"[AriaBrain]: Successfully registered document metadata & aliases for '{filename}', Sir.")

    def search(self, query: str, mongo_media_col = None) -> dict:
        """Unified query handler: searches document metadata, aliases, memories, and cached intelligence."""
        lower_q = query.lower()
        results = {"documents": [], "memories": [], "answers": []}

        # 1. Search Document Index via semantic similarity & alias matching
        try:
            doc_hits = self.doc_meta_col.query(query_texts=[query], n_results=3)
            if doc_hits and doc_hits.get("metadatas") and len(doc_hits["metadatas"][0]) > 0:
                for meta in doc_hits["metadatas"][0]:
                    results["documents"].append({
                        "filename": meta.get("filename"),
                        "title": meta.get("title"),
                        "summary": meta.get("summary")
                    })
        except Exception as e:
            print(f"[Brain Doc Search Error]: {e}")

        # 2. Fallback scan of Media Vault filenames / titles if direct vector hit is sparse
        if not results["documents"] and mongo_media_col is not None:
            # Synchronous helper to query Mongo media if accessed via async context
            pass

        # 3. Search Brain QA Cache
        try:
            brain_hits = self.brain_col.query(query_texts=[query], n_results=1)
            if brain_hits and brain_hits.get("documents") and len(brain_hits["documents"][0]) > 0:
                dist = brain_hits.get("distances", [[1.0]])[0][0]
                if dist < 0.4:  # High semantic confidence threshold
                    results["answers"].append(brain_hits["documents"][0][0])
        except Exception as e:
            print(f"[Brain Cache Search Error]: {e}")

        return results

    def search_brain(self, question: str):
        """Legacy helper matching existing main.py callers."""
        res = self.search(question)
        if res["answers"]:
            return {"confidence": 0.95, "answer": res["answers"][0]}
        if res["documents"]:
            doc_list = "\n".join([f"• **{d['title']}** ({d['filename']})\n  *{d['summary']}" for d in res["documents"]])
            return {
                "confidence": 0.96,
                "answer": f"Yes, Sir. I found documents matching your request:\n\n{doc_list}\n\nWould you like me to open, summarize, or send one of them?"
            }
        return None

    def store_knowledge(self, question: str, answer: str, topic: str, category: str, summary: str, source: str, confidence: float, verified: bool, knowledge_type: str):
        """Stores verified QA knowledge into the Brain cache."""
        self.brain_col.upsert(
            ids=[str(datetime.now(timezone.utc).timestamp())],
            documents=[answer],
            metadatas=[{"question": question, "confidence": confidence, "verified": verified}]
        )

def json_dumps_safe(obj) -> str:
    import json
    try:
        return json.dumps(obj)
    except:
        return "[]"
