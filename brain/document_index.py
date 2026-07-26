import os
import json
import re
from google import genai
from brain.models.request import BrainRequest

class DocumentIndex:
    def __init__(self, chroma_repo, mongo_repo, event_bus, api_key: str = None):
        self.chroma = chroma_repo
        self.mongo = mongo_repo
        self.events = event_bus
        self.client = genai.Client(api_key=api_key or os.getenv("GEMINI_API_KEY"))

    async def index_document(self, request: BrainRequest, filename: str, raw_text: str):
        title = filename.replace("_", " ").replace(".pdf", "").title()
        summary = raw_text[:400].replace("\n", " ")
        aliases = [title.lower(), filename.replace("_", " ").lower()]
        
        try:
            res = self.client.models.generate_content(
                model='gemini-2.0-flash',
                contents=f"Provide title, summary, aliases for: {filename}\nText: {raw_text[:1000]}"
            )
            raw = res.text.strip()
            cleaned = re.sub(r'```(?:json)?\s*', '', raw)
            cleaned = re.sub(r'\s*```', '', cleaned).strip()
            data = json.loads(cleaned)
            title = data.get("title", title)
            summary = data.get("summary", summary)
            aliases.extend(data.get("aliases", []))
        except Exception:
            pass

        doc_meta = {
            "doc_id": request.metadata.get("doc_id", "doc_1"), 
            "filename": filename, 
            "title": title, 
            "summary": summary,
            "aliases": list(set(aliases))
        }
        
        # Persist via Repositories
        if self.mongo.docs:
            await self.mongo.docs.update_one({"doc_id": doc_meta["doc_id"]}, {"$set": doc_meta}, upsert=True)
        if self.chroma.docs:
            searchable_text = f"Title: {title}. Summary: {summary}. Aliases: {', '.join(doc_meta['aliases'])}"
            self.chroma.docs.upsert(ids=[doc_meta["doc_id"]], documents=[searchable_text], metadatas=[doc_meta])

        # Emit event for decoupled subscribers
        await self.events.emit("DOCUMENT_UPLOADED", doc_meta)
        return doc_meta
