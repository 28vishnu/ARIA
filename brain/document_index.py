```python
import os
import json
import re

from brain.models.request import BrainRequest

try:
    from google import genai
except ImportError:
    genai = None


class DocumentIndex:
    def __init__(self, chroma_repo, mongo_repo, event_bus, api_key: str = None):
        self.chroma = chroma_repo
        self.mongo = mongo_repo
        self.events = event_bus

        # Strict mode must never initialize an LLM client.
        strict_no_llm = os.getenv("ARIA_STRICT_NO_LLM", "").strip().lower() in {
            "1", "true", "yes", "on"
        }

        resolved_api_key = api_key or os.getenv("GEMINI_API_KEY")

        # Keep local indexing available when credentials are absent.
        self.client = None
        if not strict_no_llm and genai is not None and resolved_api_key:
            try:
                self.client = genai.Client(api_key=resolved_api_key)
            except Exception:
                # Client initialization must not prevent local operation.
                self.client = None

    async def index_document(
        self,
        request: BrainRequest,
        filename: str,
        raw_text: str,
    ):
        title = filename.replace("_", " ").replace(".pdf", "").title()
        summary = raw_text[:400].replace("\n", " ")
        aliases = [title.lower(), filename.replace("_", " ").lower()]

        # Optional enrichment only; local metadata generation works without an LLM.
        if self.client is not None:
            try:
                res = self.client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=(
                        f"Provide title, summary, aliases for: {filename}\n"
                        f"Text: {raw_text[:1000]}"
                    ),
                )
                raw = (res.text or "").strip()
                cleaned = re.sub(r"```(?:json)?\s*", "", raw)
                cleaned = re.sub(r"\s*```", "", cleaned).strip()
                data = json.loads(cleaned)

                title = data.get("title", title)
                summary = data.get("summary", summary)
                extra_aliases = data.get("aliases", [])
                if isinstance(extra_aliases, list):
                    aliases.extend(
                        alias for alias in extra_aliases
                        if isinstance(alias, str)
                    )
            except Exception:
                # Fall back to deterministic local metadata.
                pass

        doc_meta = {
            "doc_id": request.metadata.get("doc_id", "doc_1"),
            "filename": filename,
            "title": title,
            "summary": summary,
            "aliases": sorted(set(aliases)),
        }

        # Persist via repositories when they are available.
        if self.mongo.docs is not None:
            await self.mongo.docs.update_one(
                {"doc_id": doc_meta["doc_id"]},
                {"$set": doc_meta},
                upsert=True,
            )

        if self.chroma.docs is not None:
            searchable_text = (
                f"Title: {title}. Summary: {summary}. "
                f"Aliases: {', '.join(doc_meta['aliases'])}"
            )
            self.chroma.docs.upsert(
                ids=[doc_meta["doc_id"]],
                documents=[searchable_text],
                metadatas=[doc_meta],
            )

        await self.events.emit("DOCUMENT_UPLOADED", doc_meta)
        return doc_meta
```
