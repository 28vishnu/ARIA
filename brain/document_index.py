import os
import json
import re
from google import genai

class DocumentIndex:
    def __init__(self, chroma_client, mongo_db, api_key: str = None):
        self.chroma = chroma_client
        self.meta_col = chroma_client.get_or_create_collection(name="aria_document_metadata")
        self.db_docs = mongo_db["document_metadata"] if mongo_db is not None else None
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.client = genai.Client(api_key=self.api_key) if self.api_key else None

    async def register_document(self, doc_id: str, filename: str, raw_text: str):
        """Generates rich title, summary, aliases, keywords, and entities using Gemini."""
        title = filename.replace("_", " ").replace(".pdf", "").replace(".docx", "").title()
        summary = raw_text[:400].replace("\n", " ")
        aliases = [title.lower(), filename.replace("_", " ").lower()]
        keywords = [w.strip() for w in title.split() if len(w) > 3]
        entities = []

        if self.client and len(raw_text) > 50:
            prompt = f"""
Analyze this document excerpt and provide structured metadata in strict JSON format:
Filename: {filename}
Excerpt: {raw_text[:1500]}

JSON Structure:
{{
  "title": "Clean professional title",
  "summary": "Comprehensive 2-sentence summary",
  "aliases": ["alias 1", "alias 2", "synonym or search term users might use"],
  "keywords": ["keyword1", "keyword2"],
  "entities": ["entity1", "entity2"]
}
}
"""
            try:
                res = self.client.models.generate_content(model='gemini-2.0-flash', contents=prompt)
                raw = res.text.strip()
                cleaned = re.sub(r'```(?:json)?\s*', '', raw)
                cleaned = re.sub(r'\s*```', '', cleaned).strip()
                data = json.loads(cleaned)
                
                title = data.get("title", title)
                summary = data.get("summary", summary)
                aliases.extend(data.get("aliases", []))
                keywords.extend(data.get("keywords", []))
                entities = data.get("entities", [])
            except Exception as e:
                print(f"[DocumentIndex LLM Metadata Generation Warning]: {e}")

        doc_meta = {
            "doc_id": doc_id,
            "filename": filename,
            "title": title,
            "summary": summary,
            "aliases": list(set(aliases)),
            "keywords": list(set(keywords)),
            "entities": entities
        }

        # Persist to Mongo & Chroma
        if self.db_docs is not None:
            await self.db_docs.update_one({"doc_id": doc_id}, {"$set": doc_meta}, upsert=True)

        searchable_text = f"Title: {title}. Summary: {summary}. Aliases: {', '.join(aliases)}. Keywords: {', '.join(keywords)}."
        self.meta_col.upsert(
            ids=[doc_id],
            documents=[searchable_text],
            metadatas=[{"doc_id": doc_id, "title": title, "filename": filename, "summary": summary}]
        )
        print(f"[DocumentIndex]: Successfully indexed document ID {doc_id} ('{title}'), Sir.")
        return doc_meta

    async def search(self, query: str) -> list[dict]:
        """Searches document metadata and aliases."""
        try:
            hits = self.meta_col.query(query_texts=[query], n_results=3)
            results = []
            if hits and hits.get("metadatas") and len(hits["metadatas"][0]) > 0:
                for meta in hits["metadatas"][0]:
                    results.append({
                        "id": meta.get("doc_id"),
                        "title": meta.get("title"),
                        "filename": meta.get("filename"),
                        "summary": meta.get("summary"),
                        "source": "document"
                    })
            return results
        except Exception as e:
            print(f"[DocumentIndex Search Error]: {e}")
            return []
