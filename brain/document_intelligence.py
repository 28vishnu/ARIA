import os
import logging
import asyncio
import re

logger = logging.getLogger("aria")

class DocumentIntelligence:
    def __init__(self, chroma_docs_collection, llm_router=None):
        self.docs_col = chroma_docs_collection
        self.llm_router = llm_router

    def _compute_retrieval_score(self, distance: float) -> float:
        """Converts a Chroma distance metric into a normalized confidence score (0.0 to 1.0)."""
        if distance is None:
            return 0.5
        # Assuming L2 or cosine distance where lower is closer; clamp between 0 and 1
        score = max(0.0, min(1.0, 1.0 - (distance / 2.0)))
        return round(score, 2)

    async def query_document(self, query: str, filename_filter: str = None, n_results: int = 8) -> dict:
        """Performs semantic search, preserves metadata/scores, ranks chunks, and computes confidence."""
        if self.docs_col is None:
            return {
                "success": False,
                "document": None,
                "summary": None,
                "error": "Document repository offline, Sir."
            }

        def _search():
            where_clause = {"filename": filename_filter} if filename_filter else None
            return self.docs_col.query(
                query_texts=[query],
                n_results=n_results,
                where=where_clause
            )

        try:
            res = await asyncio.to_thread(_search)
            documents = res.get("documents", [[]])[0]
            metadatas = res.get("metadatas", [[]])[0]
            distances = res.get("distances", [[]])[0]
            ids = res.get("ids", [[]])[0]

            if not documents:
                return {
                    "success": True,
                    "document": None,
                    "summary": "No relevant document passages found.",
                    "error": None
                }

            # 1. Structure and score chunks
            scored_chunks = []
            for chunk_id, text, meta, dist in zip(ids, documents, metadatas, distances):
                score = self._compute_retrieval_score(dist)
                meta_dict = meta if isinstance(meta, dict) else {}
                scored_chunks.append({
                    "id": chunk_id,
                    "text": text,
                    "filename": meta_dict.get("filename", "Unknown"),
                    "title": meta_dict.get("title", meta_dict.get("filename", "Document")),
                    "page": meta_dict.get("page", meta_dict.get("page_number")),
                    "section": meta_dict.get("section"),
                    "chunk_index": meta_dict.get("chunk_index"),
                    "distance": dist,
                    "retrieval_score": score
                })

            # 2. Group by document and rank files by highest cumulative/average evidence
            doc_groups = {}
            for chunk in scored_chunks:
                fname = chunk["filename"]
                if fname not in doc_groups:
                    doc_groups[fname] = {"filename": fname, "title": chunk["title"], "chunks": [], "scores": []}
                doc_groups[fname]["chunks"].append(chunk)
                doc_groups[fname]["scores"].append(chunk["retrieval_score"])

            # Select primary document with the highest average score or chunk count
            best_doc_key = max(doc_groups.keys(), key=lambda k: sum(doc_groups[k]["scores"]) / len(doc_groups[k]["scores"]))
            primary_group = doc_groups[best_doc_key]

            # Sort chunks within the document by retrieval score descending
            primary_group["chunks"].sort(key=lambda x: x["retrieval_score"], reverse=True)
            doc_confidence = sum(primary_group["scores"]) / len(primary_group["scores"])

            document_payload = {
                "filename": primary_group["filename"],
                "title": primary_group["title"],
                "chunks": primary_group["chunks"],
                "confidence": round(doc_confidence, 2)
            }

            return {
                "success": True,
                "document": document_payload,
                "summary": None,
                "error": None
            }
        except Exception:
            logger.exception("[DocumentIntelligence] Query execution failed")
            return {
                "success": False,
                "document": None,
                "summary": None,
                "error": "Document retrieval failed due to an internal error."
            }

    async def summarize_document(self, document_payload: dict) -> str:
        """Generates a grounded summary using LLM with anti-hallucination guardrails, or extractive fallback."""
        chunks = document_payload.get("chunks", [])
        if not chunks:
            return "No content available to summarize."

        combined_text = "\n\n--- Passage ---\n".join([c["text"] for c in chunks[:5]])

        # Grounded LLM Summarization
        if self.llm_router is not None:
            messages = [
                {
                    "role": "system",
                    "content": "You are ARIA, an advanced AI operating system. Summarise only the supplied passages. If the information is insufficient, explicitly state that. Do not add external knowledge. Use concise bullet points. Start immediately with 'Summary:'."
                },
                {
                    "role": "user",
                    "content": f"Summarise these document passages:\n\n{combined_text}"
                }
            ]
            try:
                summary = await self.llm_router.chat(messages, temperature=0.1, max_tokens=300)
                return summary
            except Exception:
                logger.warning("[DocumentIntelligence] LLM summarisation failed; falling back to extractive summary.")

        # Extractive Fallback (No external models required)
        sentences = []
        for c in chunks[:3]:
            raw_sents = re.split(r'(?<=[.!?])\s+', c["text"])
            sentences.extend([s.strip() for s in raw_sents if len(s.strip()) > 15])
        
        unique_sentences = list(dict.fromkeys(sentences))[:4]
        if unique_sentences:
            bullet_list = "\n".join([f"• {s}" for s in unique_sentences])
            return f"Summary (Extractive):\n{bullet_list}"

        return f"Summary:\n• {chunks[0]['text'][:220]}..."
