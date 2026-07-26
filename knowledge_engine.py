import re

class KnowledgeEngine:
    def __init__(self, chroma_docs, chroma_memory, mongo_media, profile_engine = None):
        self.docs_col = chroma_docs
        self.mem_col = chroma_memory
        self.media_col = mongo_media
        self.profile_engine = profile_engine

    def _extract_entities(self, text: str) -> dict:
        """Heuristic entity extractor for names, skills, organizations, and dates."""
        entities = {"skills": [], "organizations": [], "dates": []}
        text_lower = text.lower()
        
        # Skill matches
        known_skills = ["python", "java", "react", "node.js", "mongodb", "fastapi", "sql", "supabase"]
        for skill in known_skills:
            if skill in text_lower:
                entities["skills"].append(skill)
        
        # Organization matches
        if "gayatri" in text_lower: entities["organizations"].append("Gayatri Vidya Parishad College")
        if "oasis" in text_lower: entities["organizations"].append("Oasis Infobyte")
        
        # Date pattern matches
        dates = re.findall(r'\b20\d{2}\b', text)
        if dates: entities["dates"] = list(set(dates))

        return entities

    async def ingest(self, content_id: str, raw_text: str, source_type: str, metadata: dict) -> dict:
        """The single unified pipeline for all inputs: vector indexing, entity extraction, profile suggestions, and memory updates."""
        if not raw_text:
            return {"success": False, "message": "Empty text payload."}

        # 1. Vector Indexing into Chroma
        if self.docs_col:
            chunks = [raw_text[i:i+1000] for i in range(0, len(raw_text), 1000)]
            for idx, chunk in enumerate(chunks):
                self.docs_col.upsert(
                    ids=[f"{source_type}_{content_id}_{idx}"],
                    documents=[chunk],
                    metadatas=[{"source": source_type, **metadata}]
                )

        # 2. Entity Extraction
        entities = self._extract_entities(raw_text)

        # 3. Memory & Profile Suggestion generation
        profile_suggestion = None
        if entities["skills"] or entities["organizations"]:
            profile_suggestion = f"Extracted entities: Skills ({', '.join(entities['skills'])}) | Orgs ({', '.join(entities['organizations'])})"

        # 4. Long-term memory logging
        if self.mem_col:
            self.mem_col.upsert(
                ids=[f"mem_{content_id}"],
                documents=[f"Ingested {source_type}: {raw_text[:300]}..."],
                metadatas=[{"source": source_type, "type": "ingested_knowledge"}]
            )

        print(f"[Knowledge Engine]: Unified ingestion pipeline successfully processed source '{source_type}', Sir.")
        return {
            "success": True,
            "entities": entities,
            "profile_suggestion": profile_suggestion,
            "chunks_indexed": len(chunks) if 'chunks' in locals() else 0
        }
