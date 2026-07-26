import os
import logging
import asyncio

logger = logging.getLogger("aria")

class DocumentIntelligence:
    def __init__(self, chroma_docs_collection, llm_router=None):
        self.docs_col = chroma_docs_collection
        self.llm_router = llm_router

    async def query_document(self, query: str, filename_filter: str = None) -> dict:
        """Performs semantic chunk retrieval and ranks passages against the query."""
        if self.docs_col is None:
            return {"success": False, "content": "Document repository offline, Sir."}

        def _search():
            # If a specific filename filter is provided, target it; otherwise use general semantic query
            where_clause = {"filename": filename_filter} if filename_filter else None
            return self.docs_col.query(
                query_texts=[query],
                n_results=4,
                where=where_clause
            )

        try:
            res = await asyncio.to_thread(_search)
            documents = res.get("documents", [[]])[0]
            metadatas = res.get("metadatas", [[]])[0]

            if not documents:
                return {"success": True, "content": "No relevant document passages found."}

            # Simple ranking / deduplication of chunks
            ranked_chunks = []
            for doc, meta in zip(documents, metadatas):
                ranked_chunks.append({
                    "text": doc,
                    "filename": meta.get("filename", "Unknown"),
                    "title": meta.get("title", "Document")
                })

            return {
                "success": True,
                "chunks": ranked_chunks,
                "primary_filename": ranked_chunks[0]["filename"] if ranked_chunks else None
            }
        except Exception:
            logger.exception("[DocumentIntelligence] Query failed")
            return {"success": False, "content": "Document retrieval failed due to a system error."}

    async def summarize_chunks(self, chunks: list[dict]) -> str:
        """Summarizes retrieved chunks concisely following the JARVIS persona protocol."""
        if not chunks:
            return "No content available to summarize."

        combined_text = "\n\n--- Passages ---\n".join([c["text"] for c in chunks])
        
        # If LLM router is available, generate a concise grounded summary; otherwise return top passages
        if self.llm_router is not None:
            messages = [
                {
                    "role": "system",
                    "content": "You are ARIA, an advanced AI operating system. Provide a strict, concise summary of the provided text. Use bullet points. NO filler words, NO conversational intros. Start immediately with 'Summary:'."
                },
                {
                    "role": "user",
                    "content": f"Summarize these document passages:\n\n{combined_text}"
                }
            ]
            try:
                summary = await self.llm_router.chat(messages, temperature=0.1, max_tokens=250)
                return summary
            except Exception:
                logger.warning("[DocumentIntelligence] LLM summarization failed, falling back to raw chunk text.")

        # Fallback to direct chunk presentation if LLM is unavailable
        snippets = [f"• {c['text'][:180]}..." for c in chunks[:3]]
        return "Summary:\n" + "\n".join(snippets)
