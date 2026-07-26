import os
import logging
import asyncio
import re
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

logger = logging.getLogger("aria")

@dataclass
class ChunkRecord:
    id: str
    text: str
    filename: str
    title: str
    metadata: Dict[str, Any]
    distance: float
    retrieval_score: float

@dataclass
class DocumentResult:
    filename: str
    title: str
    chunks: List[ChunkRecord] = field(default_factory=list)
    confidence: float = 0.0

@dataclass
class DocumentIntelligenceResponse:
    success: bool
    document: Optional[DocumentResult] = None
    summary: Optional[str] = None
    error: Optional[str] = None

class DocumentIntelligence:
    def __init__(self, chroma_docs_collection, llm_router=None, default_metric: str = "cosine"):
        self.docs_col = chroma_docs_collection
        self.llm_router = llm_router
        self.default_metric = default_metric.lower()

    def _compute_retrieval_score(self, distance: float, metric: str) -> float:
        """Abstracted metric-aware score calibration for Cosine, Squared L2, and Inner Product."""
        if distance is None:
            return 0.5
        
        metric = metric.lower()
        if metric == "cosine":
            # Cosine distance ranges from 0.0 to 2.0 (0 = identical, 2 = opposite)
            score = max(0.0, min(1.0, 1.0 - (distance / 2.0)))
        elif metric == "l2":
            # Squared L2 distance (lower is closer; normalize via exponential decay mapping)
            import math
            score = math.exp(-distance / 2.0)
        elif metric == "ip":
            # Inner product (-1 to 1 or higher; map to 0 to 1)
            score = max(0.0, min(1.0, (distance + 1.0) / 2.0))
        else:
            score = max(0.0, min(1.0, 1.0 - (distance / 2.0)))
            
        return round(score, 2)

    async def query_document(self, query: str, filename_filter: Optional[str] = None, n_results: int = 8) -> DocumentIntelligenceResponse:
        """Performs semantic search, preserves all metadata, computes multi-signal document ranking."""
        if self.docs_col is None:
            return DocumentIntelligenceResponse(success=False, error="Document repository offline, Sir.")

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
                return DocumentIntelligenceResponse(
                    success=True,
                    document=None,
                    summary="No relevant document passages found."
                )

            # 1. Structure and score chunks preserving ALL metadata
            scored_chunks = []
            for chunk_id, text, meta, dist in zip(ids, documents, metadatas, distances):
                score = self._compute_retrieval_score(dist, self.default_metric)
                meta_dict = meta if isinstance(meta, dict) else {}
                filename = meta_dict.get("filename", "Unknown")
                title = meta_dict.get("title", filename)

                scored_chunks.append(ChunkRecord(
                    id=chunk_id,
                    text=text,
                    filename=filename,
                    title=title,
                    metadata=meta_dict,
                    distance=dist,
                    retrieval_score=score
                ))

            # 2. Group chunks by document
            doc_groups = {}
            for chunk in scored_chunks:
                fname = chunk.filename
                if fname not in doc_groups:
                    doc_groups[fname] = {
                        "filename": fname,
                        "title": chunk.title,
                        "chunks": [],
                        "scores": []
                    }
                doc_groups[fname]["chunks"].append(chunk)
                doc_groups[fname]["scores"].append(chunk.retrieval_score)

            # 3. Multi-signal document ranking (Combines average score, best chunk score, and chunk volume)
            best_doc_key = None
            best_ranking_metric = -1.0

            for fname, group in doc_groups.items():
                scores = group["scores"]
                avg_score = sum(scores) / len(scores)
                max_score = max(scores)
                volume_weight = min(1.2, 1.0 + (len(scores) * 0.05)) # Reward multi-chunk evidence
                
                composite_metric = (avg_score * 0.4) + (max_score * 0.4) + (volume_weight * 0.2)
                
                if composite_metric > best_ranking_metric:
                    best_ranking_metric = composite_metric
                    best_doc_key = fname

            primary_group = doc_groups[best_doc_key]
            primary_group["chunks"].sort(key=lambda x: x.retrieval_score, reverse=True)

            # Document confidence calculation
            doc_confidence = round(sum(primary_group["scores"]) / len(primary_group["scores"]), 2)

            document_result = DocumentResult(
                filename=primary_group["filename"],
                title=primary_group["title"],
                chunks=primary_group["chunks"],
                confidence=doc_confidence
            )

            return DocumentIntelligenceResponse(success=True, document=document_result)

        except Exception:
            logger.exception("[DocumentIntelligence] Query execution failed")
            return DocumentIntelligenceResponse(success=False, error="Document retrieval failed due to an internal error.")

    async def summarize_document(self, document_result: DocumentResult, query: str = "") -> str:
        """Generates grounded summaries with conflict warnings or query-ranked extractive fallback."""
        chunks = document_result.chunks
        if not chunks:
            return "No content available to summarize."

        combined_text = "\n\n--- Passage ---\n".join([c.text for c in chunks[:5]])

        # Grounded LLM Summarization with anti-hallucination & contradiction checks
        if self.llm_router is not None:
            messages = [
                {
                    "role": "system",
                    "content": "You are ARIA, an advanced AI operating system. Summarize only the supplied passages. If information is insufficient, explicitly state that. If multiple passages disagree or conflict, mention the disagreement instead of choosing one. Do not add external knowledge. Use concise bullet points. Start immediately with 'Summary:'."
                },
                {
                    "role": "user",
                    "content": f"Summarize these document passages:\n\n{combined_text}"
                }
            ]
            try:
                summary = await self.llm_router.chat(messages, temperature=0.1, max_tokens=300)
                return summary
            except Exception:
                logger.warning("[DocumentIntelligence] LLM summarization failed; falling back to query-ranked extractive summary.")

        # Query-Ranked Extractive Fallback (No models required)
        query_terms = set(re.findall(r'\w+', query.lower())) if query else set()
        scored_sentences = []

        for c in chunks:
            raw_sents = re.split(r'(?<=[.!?])\s+', c.text)
            for s in raw_sents:
                s_clean = s.strip()
                if len(s_clean) > 15:
                    # Score by term overlap with query
                    s_terms = set(re.findall(r'\w+', s_clean.lower()))
                    overlap = len(query_terms.intersection(s_terms)) if query_terms else 1
                    scored_sentences.append((overlap, s_clean))

        # Sort by query term overlap descending
        scored_sentences.sort(key=lambda x: x[0], reverse=True)
        unique_sentences = list(dict.fromkeys([s[1] for s in scored_sentences]))[:4]

        if unique_sentences:
            bullet_list = "\n".join([f"• {s}" for s in unique_sentences])
            return f"Summary (Extractive):\n{bullet_list}"

        return f"Summary:\n• {chunks[0].text[:220]}..."
