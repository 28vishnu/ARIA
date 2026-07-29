import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Union, Any
from pypdf import PdfReader
from sentence_transformers import SentenceTransformer

logger = logging.getLogger("aria")


class DocumentIntelligence:
    """
    Handles document ingestion, extraction, summarisation and storage.
    """

    def __init__(
        self,
        memory_engine=None,
        llm_router=None,
        vector_db=None
    ):
        self.memory_engine = memory_engine
        self.llm_router = llm_router
        self.vector_db = vector_db

        self.embedding_model = SentenceTransformer(
            "all-MiniLM-L6-v2"
        )

    async def process_document(
        self,
        file_path: str,
        session_id: str
    ):
        """
        Complete document pipeline.
        """

        # Step 1: Extract pages
        pages = await self.extract_text(file_path)

        full_text = "\n".join(
            page["text"]
            for page in pages
        )

        # Step 2: Chunk text with page tracking
        chunks = self.chunk_text_with_pages(pages)

        # Step 3: Summarise
        summary = await self.summarize(full_text)

        document_metadata = {
            "file_path": file_path,
            "document_name": Path(file_path).name
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
        Returns a list of dicts: [{"page": 1, "text": "..."}, ...]
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
                text = page.extract_text()

                if text:
                    pages.append({
                        "page": page_number,
                        "text": text
                    })

            return pages

        raise ValueError(f"Unsupported file type: {suffix}")

    def chunk_text(
        self,
        text: str,
        chunk_size: int = 1000,
        overlap: int = 200
    ) -> List[str]:
        """
        Split text into overlapping chunks.
        """

        chunks = []

        start = 0

        while start < len(text):

            end = start + chunk_size

            chunks.append(text[start:end])

            start += chunk_size - overlap

        return chunks

    def chunk_text_with_pages(
        self,
        pages,
        chunk_size=1000,
        overlap=200
    ):
        """
        Split text into chunks while preserving page numbers.
        """

        chunks = []

        for page in pages:

            text = page["text"]
            page_number = page["page"]

            start = 0

            while start < len(text):

                end = start + chunk_size

                chunks.append({
                    "text": text[start:end],
                    "page": page_number
                })

                start += chunk_size - overlap

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
        metadata: Optional[dict] = None
    ):
        """
        Store semantic embeddings in ChromaDB.
        """

        if self.vector_db is None:
            return

        embeddings = self.embedding_model.encode(
            [c["text"] for c in chunks],
            convert_to_numpy=True
        ).tolist()

        metadata = metadata or {}
        document_id = metadata.get("document_name", "default")

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
            documents=[c["text"] for c in chunks],
            embeddings=embeddings,
            metadatas=metadatas
        )

        logger.info(
            "[DocumentAI] Stored %d vectors for %s.",
            len(chunks),
            document_id
        )

    async def semantic_search(
        self,
        session_id: str,
        query: str,
        limit: int = 5
    ):
        """
        Retrieve the most relevant chunks using semantic similarity.
        """

        if self.vector_db is None:
            return []

        query_embedding = self.embedding_model.encode(
            query,
            convert_to_numpy=True
        ).tolist()

        results = self.vector_db.query(
            query_embeddings=[query_embedding],
            n_results=limit,
            where={
                "session_id": session_id
            }
        )

        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]

        return [
            {
                "text": doc,
                "page": meta.get("page", "?"),
                "document": meta.get("document_name", "Unknown")
            }
            for doc, meta in zip(documents, metadatas)
        ]

    async def hybrid_search(
        self,
        session_id: str,
        query: str,
        limit: int = 5
    ):
        """
        Combine semantic and keyword retrieval.
        """

        semantic = await self.semantic_search(
            session_id=session_id,
            query=query,
            limit=limit
        )

        keyword = await self.retrieve_chunks(
            session_id=session_id,
            query=query,
            limit=limit
        )

        merged = []

        seen = set()

        for chunk in semantic + keyword:

            text = chunk["text"] if isinstance(chunk, dict) else chunk

            if text not in seen:

                merged.append(chunk)

                seen.add(text)

        return merged[:limit]

    async def retrieve_chunks(
        self,
        session_id: str,
        query: str,
        limit: int = 5
    ):
        """
        Retrieve document chunks related to a query.
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

    async def answer_question(
        self,
        session_id: str,
        question: str,
        state: Optional[dict] = None
    ):
        """
        Answer a question using previously uploaded documents.
        """

        if state:

            previous = state.get(
                "last_document_question"
            )

            if previous:

                question = (
                    previous
                    + "\nFollow-up: "
                    + question
                )

        chunks = await self.hybrid_search(
            session_id=session_id,
            query=question
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

        context = "\n\n".join(
            f"[Document: {chunk['document']} | Page {chunk['page']}]\n{chunk['text']}"
            for chunk in chunks
        )

        messages = [
            {
                "role": "system",
                "content": (
                    "You are ARIA's document assistant.\n"
                    "Answer ONLY using the supplied document context.\n"
                    "If multiple documents are referenced, clearly mention which document and page the information came from.\n"
                    "Example:\n"
                    "'According to Italy_Guide.pdf, Page 4...'\n"
                    "If the answer is absent, reply:\n"
                    "'I couldn't find that information in your uploaded documents.'"
                )
            },
            {
                "role": "user",
                "content": f"""
Document Context:

{context}

Question:

{question}
"""
            }
        ]

        answer = await self.llm_router.chat(messages)

        if not answer or not answer.strip():
            return (
                "I couldn't find that information in your uploaded documents."
            )

        return answer
