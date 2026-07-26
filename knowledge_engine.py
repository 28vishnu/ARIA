class KnowledgeEngine:
    def __init__(self, chroma_docs, chroma_memory, mongo_media):
        self.docs_col = chroma_docs
        self.mem_col = chroma_memory
        self.media_col = mongo_media

    async def ingest_unified_stream(self, content_id: str, raw_text: str, source_type: str, metadata: dict):
        """Unified pipeline routing any extracted text into vector indices and knowledge stores."""
        if not raw_text: return
        
        # Index into Chroma Vector Database for semantic retrieval
        if self.docs_col:
            chunks = [raw_text[i:i+1000] for i in range(0, len(raw_text), 1000)]
            for idx, chunk in enumerate(chunks):
                self.docs_col.upsert(
                    ids=[f"{source_type}_{content_id}_{idx}"],
                    documents=[chunk],
                    metadatas=[{"source": source_type, **metadata}]
                )
        print(f"[Knowledge Engine]: Successfully unified and indexed content from source '{source_type}', Sir.")
