"""Local-first document metadata indexing for ARIA.

LLM enrichment is optional and disabled by default. Documents can still be
indexed using deterministic local metadata when no provider is configured.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from brain.models.request import BrainRequest

logger = logging.getLogger("aria.document_index")

try:
    from google import genai
except ImportError:  # Optional dependency; local indexing must still work.
    genai = None


def _env_enabled(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


class DocumentIndex:
    def __init__(self, chroma_repo, mongo_repo, event_bus, api_key: str | None = None):
        self.chroma = chroma_repo
        self.mongo = mongo_repo
        self.events = event_bus
        self.client = None

        # Match ARIA's strict-by-default LLM policy. Enrichment is enabled only
        # when ARIA_STRICT_NO_LLM is explicitly disabled and a key is available.
        strict_no_llm = _env_enabled("ARIA_STRICT_NO_LLM", default="1")
        resolved_api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not strict_no_llm and genai is not None and resolved_api_key:
            try:
                self.client = genai.Client(api_key=resolved_api_key)
            except Exception:
                logger.warning("Gemini client initialization failed; using local metadata.", exc_info=True)

    async def index_document(
        self, request: BrainRequest, filename: str, raw_text: str
    ) -> dict[str, Any]:
        metadata = getattr(request, "metadata", None) or {}
        safe_filename = str(filename or "document")
        text = str(raw_text or "")
        title = re.sub(r"\s+", " ", safe_filename.rsplit(".", 1)[0].replace("_", " ")).strip().title()
        summary = re.sub(r"\s+", " ", text).strip()[:400]
        aliases = [title.casefold(), safe_filename.replace("_", " ").casefold()]

        # Optional enrichment; this path is unreachable in strict no-LLM mode.
        if self.client is not None and text.strip():
            try:
                response = self.client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=(
                        "Return JSON with title, summary, and aliases for this document.\n"
                        f"Filename: {safe_filename}\nText: {text[:1000]}"
                    ),
                )
                raw = str(getattr(response, "text", "") or "").strip()
                cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.IGNORECASE).strip()
                data = json.loads(cleaned)
                if isinstance(data, dict):
                    candidate_title = data.get("title")
                    candidate_summary = data.get("summary")
                    if isinstance(candidate_title, str) and candidate_title.strip():
                        title = candidate_title.strip()[:500]
                    if isinstance(candidate_summary, str) and candidate_summary.strip():
                        summary = candidate_summary.strip()[:2000]
                    extra_aliases = data.get("aliases", [])
                    if isinstance(extra_aliases, list):
                        aliases.extend(alias.strip() for alias in extra_aliases if isinstance(alias, str) and alias.strip())
            except Exception:
                logger.debug("Optional document enrichment failed; retaining local metadata.", exc_info=True)

        doc_id = str(metadata.get("doc_id") or metadata.get("document_id") or safe_filename)[:500]
        doc_meta = {
            "doc_id": doc_id,
            "filename": safe_filename[:500],
            "title": title,
            "summary": summary,
            "aliases": sorted(set(aliases)),
            "external_llm_used": bool(self.client is not None),
        }

        mongo_docs = getattr(self.mongo, "docs", None) if self.mongo is not None else None
        if mongo_docs is not None:
            await mongo_docs.update_one({"doc_id": doc_id}, {"$set": doc_meta}, upsert=True)

        chroma_docs = getattr(self.chroma, "docs", None) if self.chroma is not None else None
        if chroma_docs is not None:
            searchable_text = f"Title: {title}. Summary: {summary}. Aliases: {', '.join(doc_meta['aliases'])}"
            chroma_docs.upsert(ids=[doc_id], documents=[searchable_text], metadatas=[doc_meta])

        # The repository EventBus exposes publish_safe, not emit. Avoid allowing
        # optional event notification to break a successful local index operation.
        publisher = getattr(self.events, "publish_safe", None) if self.events is not None else None
        if callable(publisher):
            try:
                publisher("DOCUMENT_UPLOADED", doc_meta)
            except Exception:
                logger.warning("Document indexed but event publication failed.", exc_info=True)
        else:
            emitter = getattr(self.events, "emit", None) if self.events is not None else None
            if callable(emitter):
                try:
                    await emitter("DOCUMENT_UPLOADED", doc_meta)
                except Exception:
                    logger.warning("Document indexed but event emission failed.", exc_info=True)

        return doc_meta
