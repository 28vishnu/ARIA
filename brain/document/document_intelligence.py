import hashlib
import logging
import re
import time
import gc
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Union, Any
from pypdf import PdfReader

logger = logging.getLogger("aria")


class DocumentIntelligence:
    """
    Handles document ingestion, extraction, summarisation, semantic vector indexing,
    hybrid search retrieval, and question answering.
    """

    def __init__(
        self,
        memory_engine=None,
        llm_router=None,
        vector_db=None,
        document_repository=None
    ):
        self.memory_engine = memory_engine
        self.llm_router = llm_router
        self.vector_db = vector_db
        self.document_repository = document_repository

        self._embedding_cache: Dict[str, List[float]] = {}

    def unload_embedding_model(self):
        """
        Run garbage collection after document operations.
        Embeddings are generated remotely, so no local ML model
        needs to be unloaded.
        """
        gc.collect()

    async def process_document(
        self,
        file_path: str,
        session_id: str,
        document_name: Optional[str] = None
    ):
        """
        Complete document pipeline with performance timing.
        """
        t_start = time.perf_counter()

        # Step 1: Extract pages
        t0 = time.perf_counter()
        pages = await self.extract_text(file_path)
        t_extract = time.perf_counter() - t0

        full_text = "\n".join(
            page["text"]
            for page in pages
        )

        # Step 2: Chunk text with page tracking
        t0 = time.perf_counter()
        chunks = self.chunk_text_with_pages(pages)
        t_chunk = time.perf_counter() - t0

        # Step 3: Summarise
        summary = await self.summarize(full_text)

        actual_document_name = (
            str(document_name).strip()
            if document_name
            else Path(file_path).name
        )

        document_metadata = {
            "file_path": file_path,
            "document_name": actual_document_name
        }

        # Step 4: Store (if memory is available)
        if self.memory_engine:
            try:
                await self.store(
                    session_id=session_id,
                    summary=summary,
                    document_text=full_text,
                    metadata=document_metadata
                )
                await self.store_chunks(
                    session_id=session_id,
                    chunks=chunks,
                    metadata=document_metadata
                )
                await self.store_vectors(
                    session_id=session_id,
                    chunks=chunks,
                    metadata=document_metadata
                )
            except Exception as e:
                logger.exception(
                    "[DocumentAI] Failed to store document: %s",
                    e
                )

        t_total = time.perf_counter() - t_start
        logger.info(
            "[DocumentAI] Processed %s in %.2fs (Extract: %.2fs, Chunk: %.2fs)",
            actual_document_name,
            t_total,
            t_extract,
            t_chunk
        )

        return {
            "success": True,
            "text": full_text,
            "summary": summary,
            "chunks": chunks,
            "pages": pages
        }

    async def extract_text(
        self,
        file_path: str
    ) -> List[Dict[str, Union[int, str]]]:
        """
        Extract text with page numbers from TXT and PDF files.
        Falls back to OCR for scanned PDFs if pypdf returns empty pages.
        """
        suffix = Path(file_path).suffix.lower()

        if suffix == ".txt":
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
                return [{
                    "page": 1,
                    "text": content
                }]

        if suffix == ".pdf":
            reader = PdfReader(file_path)
            pages = []

            for page_number, page in enumerate(reader.pages, start=1):
                try:
                    # Preserve the visual layout of tables, schedules,
                    # columns, forms, etc. whenever pypdf supports it.
                    text = page.extract_text(
                        extraction_mode="layout"
                    ) or ""
                except TypeError:
                    # Fallback for older pypdf versions.
                    text = page.extract_text() or ""

                # OCR Fallback if page text is empty
                if not text.strip():
                    try:
                        import pytesseract
                        from pdf2image import convert_from_path

                        images = convert_from_path(
                            file_path,
                            first_page=page_number,
                            last_page=page_number
                        )

                        if images:
                            ocr_text = pytesseract.image_to_string(
                                images[0]
                            )

                            if ocr_text.strip():
                                text = ocr_text.strip()
                                logger.info(
                                    "[DocumentAI OCR] Successfully extracted page %d via OCR",
                                    page_number
                                )

                    except Exception as ocr_err:
                        logger.warning(
                            "[DocumentAI OCR] OCR failed on page %d: %s",
                            page_number,
                            ocr_err
                        )

                if text.strip():
                    pages.append({
                        "page": page_number,
                        "text": text.strip()
                    })

            return pages

        raise ValueError(f"Unsupported file type: {suffix}")

    def chunk_text_with_pages(
        self,
        pages,
        target_chunk_size=1000,
        max_chunk_size=1200
    ):
        """
        Split text into chunks by paragraphs while preserving page numbers.
        """
        chunks = []

        for page in pages:
            text = page["text"]
            page_number = page["page"]

            # Preserve line spacing/alignment from layout-aware PDF extraction.
            # This is important for tables, timetables, schedules and columns.
            paragraphs = [
                line.rstrip()
                for line in text.splitlines()
                if line.strip()
            ]
            current_chunk = ""

            for paragraph in paragraphs:
                if len(current_chunk) + len(paragraph) + 1 <= target_chunk_size:
                    current_chunk = f"{current_chunk}\n{paragraph}".strip()
                else:
                    if current_chunk:
                        chunks.append({
                            "text": current_chunk,
                            "page": page_number
                        })

                    if len(paragraph) > max_chunk_size:
                        start = 0
                        while start < len(paragraph):
                            end = start + target_chunk_size
                            chunks.append({
                                "text": paragraph[start:end],
                                "page": page_number
                            })
                            start += target_chunk_size
                        current_chunk = ""
                    else:
                        current_chunk = paragraph

            if current_chunk:
                chunks.append({
                    "text": current_chunk,
                    "page": page_number
                })

        return chunks

    async def summarize(
        self,
        text: str
    ) -> str:
        """
        Generate an AI summary of a document.
        """
        if not self.llm_router:
            return text[:1000]

        messages = [
            {
                "role": "system",
                "content": (
                    "You are ARIA's document analyst. "
                    "Summarise the document clearly using headings, "
                    "bullet points, and key takeaways."
                )
            },
            {
                "role": "user",
                "content": text
            }
        ]

        summary = await self.llm_router.chat(messages)

        return summary

    async def store(
        self,
        session_id: str,
        summary: str,
        document_text: str,
        metadata: Optional[dict] = None
    ):
        """
        Store a processed document summary as long-term memory.
        """
        if self.memory_engine is None:
            return

        now = datetime.now(timezone.utc).isoformat()
        metadata = metadata or {}

        await self.memory_engine.memory_col.update_one(
            {
                "key": f"document_{session_id}_{metadata.get('document_name', 'default')}"
            },
            {
                "$set": {
                    "key": f"document_{session_id}_{metadata.get('document_name', 'default')}",
                    "value": summary,
                    "document_text": document_text,
                    "document_name": metadata.get("document_name"),
                    "category": "document",
                    "memory_type": "document_summary",
                    "importance": "high",
                    "confidence": 1.0,
                    "metadata": metadata,
                    "updated_at": now
                },
                "$setOnInsert": {
                    "first_seen": now,
                    "last_used": now
                }
            },
            upsert=True
        )

    async def store_chunks(
        self,
        session_id: str,
        chunks: list[dict],
        metadata: Optional[dict] = None
    ):
        """
        Store every document chunk separately.
        """
        if self.memory_engine is None:
            return

        now = datetime.now(timezone.utc).isoformat()
        metadata = metadata or {}
        doc_name = metadata.get("document_name", "default")

        for index, chunk in enumerate(chunks):
            await self.memory_engine.memory_col.update_one(
                {
                    "key": f"document_chunk_{session_id}_{doc_name}_{index}"
                },
                {
                    "$set": {
                        "key": f"document_chunk_{session_id}_{doc_name}_{index}",
                        "value": chunk["text"],
                        "page": chunk["page"],
                        "document_name": metadata.get("document_name"),
                        "category": "document_chunk",
                        "memory_type": "document_chunk",
                        "chunk_index": index,
                        "importance": "medium",
                        "confidence": 1.0,
                        "metadata": metadata,
                        "updated_at": now
                    },
                    "$setOnInsert": {
                        "first_seen": now,
                        "last_used": now
                    }
                },
                upsert=True
            )

    async def store_vectors(
        self,
        session_id: str,
        chunks: list[dict],
        metadata: Optional[dict] = None,
        batch_size: int = 8
    ):
        """
        Store semantic embeddings in ChromaDB using caching, batching,
        and remote Gemini API embedding generation.
        """
        if self.vector_db is None:
            return

        t0 = time.perf_counter()
        metadata = metadata or {}
        document_id = metadata.get("document_name", "default")

        texts = [c["text"] for c in chunks]
        embeddings = []

        # Batch & Cache Encoding
        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i:i + batch_size]
            batch_to_encode = []
            batch_indices_to_encode = []

            for idx, txt in enumerate(batch_texts):
                txt_hash = hashlib.md5(txt.encode("utf-8")).hexdigest()
                if txt_hash in self._embedding_cache:
                    embeddings.append(self._embedding_cache[txt_hash])
                else:
                    batch_to_encode.append(txt)
                    batch_indices_to_encode.append(len(embeddings))
                    embeddings.append(None)  # Placeholder

            if batch_to_encode:
                encoded_batch = await self.llm_router.embed(
                    batch_to_encode,
                    task_type="RETRIEVAL_DOCUMENT"
                )

                for sub_idx, emb in enumerate(encoded_batch):
                    target_pos = batch_indices_to_encode[sub_idx]
                    embeddings[target_pos] = emb
                    txt_hash = hashlib.md5(batch_to_encode[sub_idx].encode("utf-8")).hexdigest()
                    self._embedding_cache[txt_hash] = emb

        ids = [
            f"{session_id}_{document_id}_{i}"
            for i in range(len(chunks))
        ]

        metadatas = []
        for i in range(len(chunks)):
            data = dict(metadata)
            data["session_id"] = session_id
            data["chunk_index"] = i
            data["page"] = chunks[i]["page"]
            data["document_name"] = metadata.get("document_name")
            metadatas.append(data)

        try:
            self.vector_db.delete(ids=ids)
        except Exception:
            pass

        self.vector_db.add(
            ids=ids,
            documents=texts,
            embeddings=embeddings,
            metadatas=metadatas
        )

        t_store = time.perf_counter() - t0
        logger.info(
            "[DocumentAI] Stored %d vectors for %s in %.2fs.",
            len(chunks),
            document_id,
            t_store
        )

        # Prevent embedding cache from growing indefinitely.
        if len(self._embedding_cache) > 100:
            self._embedding_cache.clear()

        self.unload_embedding_model()

    def _parse_query_filters(self, query: str) -> tuple[str, dict]:
        """
        Extracts specific document name and page number filters from the query string.
        Returns cleaned_query, filter_dict
        """
        where_filter = {}
        cleaned_query = query

        # Parse document filter (e.g. "Only in Italy.pdf" or "document:Italy.pdf")
        doc_match = re.search(r"(?:only\s+in|document:)\s*([a-zA-Z0-9_\-\.\s]+\.(?:pdf|txt))", cleaned_query, re.IGNORECASE)
        if doc_match:
            doc_name = doc_match.group(1).strip()
            where_filter["document_name"] = doc_name
            cleaned_query = re.sub(re.escape(doc_match.group(0)), "", cleaned_query, flags=re.IGNORECASE)

        # Parse page filter (e.g. "Only page 5" or "page:5")
        page_match = re.search(r"(?:only\s+page|page:)\s*(\d+)", cleaned_query, re.IGNORECASE)
        if page_match:
            page_num = int(page_match.group(1))
            where_filter["page"] = page_num
            cleaned_query = re.sub(re.escape(page_match.group(0)), "", cleaned_query, flags=re.IGNORECASE)

        return cleaned_query.strip(), where_filter

    async def semantic_search(
        self,
        session_id: str,
        query: str,
        limit: int = 5,
        filters: Optional[dict] = None
    ):
        """
        Retrieve the most relevant chunks using semantic similarity via remote Gemini API embeddings.
        """
        if self.vector_db is None:
            return []

        t0 = time.perf_counter()

        conditions = [
            {"session_id": {"$eq": session_id}}
        ]

        if filters:
            for k, v in filters.items():
                conditions.append({
                    k: {"$eq": v}
                })

        if len(conditions) == 1:
            where_clause = conditions[0]
        else:
            where_clause = {
                "$and": conditions
            }

        try:
            query_embeddings = await self.llm_router.embed(
                [query],
                task_type="RETRIEVAL_QUERY"
            )

            query_embedding = query_embeddings[0]

            results = self.vector_db.query(
                query_embeddings=[query_embedding],
                n_results=limit,
                where=where_clause
            )

            documents = results.get(
                "documents",
                [[]]
            )[0]

            metadatas = results.get(
                "metadatas",
                [[]]
            )[0]

            output = [
                {
                    "text": doc,
                    "page": meta.get("page", "?"),
                    "document": meta.get(
                        "document_name",
                        "Unknown"
                    )
                }
                for doc, meta in zip(
                    documents,
                    metadatas
                )
            ]

            logger.info(
                "[DocumentAI] Semantic search returned %d items in %.3fs.",
                len(output),
                time.perf_counter() - t0
            )

            return output

        finally:
            self.unload_embedding_model()

    async def retrieve_chunks(
        self,
        session_id: str,
        query: str,
        limit: int = 5,
        filters: Optional[dict] = None
    ):
        """
        Retrieve document chunks related to a query via keyword matching and filtering.
        """
        if self.memory_engine is None:
            return []

        cursor = self.memory_engine.memory_col.find(
            {
                "category": "document_chunk",
                "key": {
                    "$regex": f"document_chunk_{session_id}_"
                }
            }
        )

        chunks = await cursor.to_list(length=100)
        if not chunks:
            return []

        # Apply metadata filters if present
        if filters:
            if "document_name" in filters:
                target_document = filters["document_name"]

                chunks = [
                    c for c in chunks
                    if c.get("document_name") == target_document
                ]

                logger.info(
                    "[DocumentAI] Keyword retrieval restricted to '%s': %d chunks remain.",
                    target_document,
                    len(chunks)
                )

            if "page" in filters:
                chunks = [
                    c for c in chunks
                    if c.get("page") == filters["page"]
                ]

        query_words = {
            word.lower()
            for word in query.split()
            if len(word) > 2
        }

        scored = []
        for chunk in chunks:
            text = chunk.get("value", "")
            score = sum(
                1
                for word in query_words
                if word in text.lower()
            )
            scored.append(
                (
                    score,
                    {
                        "text": text,
                        "page": chunk.get("page", "?"),
                        "document": chunk.get("document_name", "Unknown")
                    }
                )
            )

        scored.sort(
            reverse=True,
            key=lambda x: x[0]
        )

        return [
            chunk
            for score, chunk in scored[:limit]
            if score > 0
        ]

    async def hybrid_search(
        self,
        session_id: str,
        query: str,
        limit: int = 5
    ):
        """
        Combine semantic and keyword retrieval using Reciprocal Rank Fusion (RRF).
        """
        clean_query, filters = self._parse_query_filters(query)

        semantic = await self.semantic_search(
            session_id=session_id,
            query=clean_query,
            limit=limit * 2,
            filters=filters
        )

        keyword = await self.retrieve_chunks(
            session_id=session_id,
            query=clean_query,
            limit=limit * 2,
            filters=filters
        )

        # Reciprocal Rank Fusion (RRF)
        rrf_scores: Dict[str, float] = {}
        chunk_map: Dict[str, dict] = {}
        k = 60

        for rank, item in enumerate(semantic):
            txt = item["text"]
            chunk_map[txt] = item
            rrf_scores[txt] = rrf_scores.get(txt, 0.0) + (1.0 / (k + rank + 1))

        for rank, item in enumerate(keyword):
            txt = item["text"]
            chunk_map[txt] = item
            rrf_scores[txt] = rrf_scores.get(txt, 0.0) + (1.0 / (k + rank + 1))

        sorted_chunks = sorted(
            rrf_scores.keys(),
            key=lambda t: rrf_scores[t],
            reverse=True
        )

        return [chunk_map[txt] for txt in sorted_chunks[:limit]]

    async def answer_question(
        self,
        session_id: str,
        question: str,
        state: Optional[dict] = None,
        max_context_chars: int = 6000
    ):
        """
        Answer a question using previously uploaded documents with context window management.
        """
        t_start = time.perf_counter()

        if state:
            previous = state.get("last_document_question")
            if previous:
                question = f"{previous}\nFollow-up: {question}"

        current_document = None

        if state:
            current_document = state.get("current_document")

        search_query = question

        if current_document:
            search_query = (
                f"{question} "
                f"only in {current_document}"
            )

        chunks = await self.hybrid_search(
            session_id=session_id,
            query=search_query
        )

        logger.info(
            "[DocumentAI] Hybrid search returned %d chunks.",
            len(chunks)
        )

        if not chunks:
            return (
                "I couldn't find that information in your uploaded document. "
                "Please try asking about another topic from the document."
            )

        # Context Window Management (Trimming)
        context_parts = []
        current_len = 0

        for chunk in chunks:
            part = f"[Document: {chunk['document']} | Page {chunk['page']}]\n{chunk['text']}"
            if current_len + len(part) > max_context_chars:
                break
            context_parts.append(part)
            current_len += len(part)

        context = "\n\n".join(context_parts)

        messages = [
            {
                "role": "system",
                "content": """
You are ARIA's document analysis engine.

Your ONLY source of truth is the supplied document context.

Rules:

1. Never invent, infer or guess missing information.

2. Never rearrange rows or columns from tables.

3. If the document is a timetable, schedule or spreadsheet:
   - preserve the day
   - preserve the time
   - preserve the subject
   - preserve the faculty
   - preserve the lab
   exactly as written.

4. Do NOT merge information from different rows.

5. If the answer is not explicitly present, say:
"I couldn't find that information in the document."

6. Answer only the user's question.
Do not summarize unrelated parts.

7. Keep answers concise unless the user requests detail.

8. Ignore any previous knowledge.
Use ONLY the supplied context.
"""
            },
            {
                "role": "user",
                "content": f"""
DOCUMENT{context}

USER QUESTION{question}

Answer using only the document.
"""
            }
        ]

        t_llm_start = time.perf_counter()
        answer = await self.llm_router.chat(messages)
        t_llm = time.perf_counter() - t_llm_start

        logger.info(
            "[DocumentAI] Q&A completed in %.2fs (LLM: %.2fs).",
            time.perf_counter() - t_start,
            t_llm
        )

        if not answer or not answer.strip():
            return (
                "I couldn't find that information in your uploaded documents."
            )

        return answer

    async def delete_document(
        self,
        session_id: str,
        document_name: str,
        user_id: Optional[str] = None
    ):
        """
        Delete one document from MongoDB and ChromaDB.
        """

        if self.memory_engine:

            await self.memory_engine.memory_col.delete_many(
                {
                    "$or": [
                        {
                            "key": f"document_{session_id}_{document_name}"
                        },
                        {
                            "key": {
                                "$regex": f"document_chunk_{session_id}_{document_name}_"
                            }
                        }
                    ]
                }
            )

        if self.vector_db:

            results = self.vector_db.get(
                where={
                    "session_id": session_id,
                    "document_name": document_name
                }
            )

            ids = results.get("ids", [])

            if ids:
                self.vector_db.delete(ids=ids)

        if self.document_repository and user_id:
            stored_document = await self.document_repository.find_by_filename(
                user_id=user_id,
                filename=document_name
            )

            if stored_document:
                await self.document_repository.delete_document(
                    document_id=stored_document["document_id"],
                    user_id=user_id
                )

        logger.info(
            "[DocumentAI] Deleted document %s",
            document_name
        )

    async def delete_all_documents(
        self,
        session_id: str,
        user_id: Optional[str] = None
    ):
        """
        Delete every uploaded document for a session.
        """

        if self.memory_engine:

            session_pattern = re.escape(str(session_id))

            await self.memory_engine.memory_col.delete_many(
                {
                    "$or": [
                        {
                            "key": {
                                "$regex": f"^document_{session_pattern}_"
                            }
                        },
                        {
                            "key": {
                                "$regex": f"^document_chunk_{session_pattern}_"
                            }
                        }
                    ]
                }
            )

        if self.vector_db:

            results = self.vector_db.get(
                where={
                    "session_id": session_id
                }
            )

            ids = results.get("ids", [])

            if ids:
                self.vector_db.delete(ids=ids)

        if self.document_repository and user_id:
            await self.document_repository.delete_all_user_documents(
                user_id=user_id
            )

        logger.info(
            "[DocumentAI] Deleted all documents."
        )

    async def reindex_documents(
        self,
        session_id: str
    ):
        """
        Rebuild semantic vectors.
        """

        logger.info(
            "[DocumentAI] Reindex requested for %s",
            session_id
        )

        # Future implementation
