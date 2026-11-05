"""Bounded, metadata-only academic search adapters for arXiv and OpenAlex.

Search results are evidence pointers, not permission to redistribute article text.
The adapters return abstracts only when the provider returns them; they do not
download full papers or use an LLM.
"""
from __future__ import annotations

import asyncio
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

ARXIV_API = "https://export.arxiv.org/api/query"
OPENALEX_API = "https://api.openalex.org/works"
USER_AGENT = "JARVISKnowledge/1.0 (source-backed academic search)"
MAX_QUERY_CHARS = 300


def _query(value: str) -> str:
    query = re.sub(r"\s+", " ", str(value or "")).strip()
    if not query:
        raise ValueError("Academic search query must not be empty")
    return query[:MAX_QUERY_CHARS]


def _limit(value: int) -> int:
    return max(1, min(int(value), 10))


def _valid_result_url(value: Any) -> str:
    url = str(value or "").strip()
    try:
        parsed = urlparse(url)
    except ValueError:
        return ""
    return url if parsed.scheme == "https" and parsed.hostname else ""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _get(client: Any, url: str, *, params: dict[str, Any], timeout: float):
    response = await client.get(url, params=params, timeout=timeout,
                                headers={"User-Agent": USER_AGENT, "Accept": "application/atom+xml, application/json"})
    response.raise_for_status()
    return response


async def search_arxiv(query: str, *, limit: int = 5, timeout: float = 10.0,
                       client: Any = None) -> list[dict[str, Any]]:
    """Search recent/relevant arXiv records; preserve preprint and date labels."""
    q = _query(query)
    owns_client = client is None
    http = client or httpx.AsyncClient()
    try:
        response = await _get(http, ARXIV_API, params={
            "search_query": f"all:{q}", "start": 0, "max_results": _limit(limit),
            "sortBy": "relevance", "sortOrder": "descending",
        }, timeout=float(timeout))
        root = ET.fromstring(response.text)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        records = []
        for entry in root.findall("atom:entry", ns):
            title = " ".join((entry.findtext("atom:title", default="", namespaces=ns)).split())
            summary = " ".join((entry.findtext("atom:summary", default="", namespaces=ns)).split())
            link = next((item.get("href", "") for item in entry.findall("atom:link", ns)
                         if item.get("rel") == "alternate"), "")
            link = _valid_result_url(link)
            paper_id = entry.findtext("atom:id", default="", namespaces=ns).rsplit("/", 1)[-1]
            if not title or not link:
                continue
            records.append({
                "source": "arxiv", "source_id": paper_id, "title": title,
                "content": summary[:12000], "url": link,
                "publication_date": entry.findtext("atom:published", default="", namespaces=ns),
                "updated_at": entry.findtext("atom:updated", default="", namespaces=ns),
                "authors": [a.findtext("atom:name", default="", namespaces=ns)
                            for a in entry.findall("atom:author", ns)],
                "categories": [c.get("term", "") for c in entry.findall("atom:category", ns)],
                "document_type": "preprint", "verification_status": "provider_metadata",
                "retrieved_at": _now(),
                "license": "Abstract metadata only; full-text reuse depends on the paper-specific license.",
                "attribution": "arXiv record; cite the linked abstract and version.",
            })
        return records
    finally:
        if owns_client:
            await http.aclose()


def _abstract_from_inverted_index(index: Any, max_chars: int = 12000) -> str:
    if not isinstance(index, dict):
        return ""
    words: dict[int, str] = {}
    for token, positions in index.items():
        if not isinstance(positions, list):
            continue
        for position in positions:
            if isinstance(position, int) and 0 <= position < 20000:
                words.setdefault(position, str(token))
    return " ".join(words[index] for index in sorted(words))[:max_chars]


async def search_openalex(query: str, *, limit: int = 5, timeout: float = 10.0,
                          client: Any = None, api_key: str | None = None) -> list[dict[str, Any]]:
    """Search OpenAlex works metadata; abstracts remain attributed and rights-aware."""
    q = _query(query)
    owns_client = client is None
    http = client or httpx.AsyncClient()
    key = api_key if api_key is not None else os.getenv("OPENALEX_API_KEY", "")
    params: dict[str, Any] = {
        "search": q, "per-page": _limit(limit),
        "select": "id,doi,title,publication_year,publication_date,authorships,primary_location,open_access,abstract_inverted_index,type",
    }
    if key:
        params["api_key"] = key
    try:
        response = await _get(http, OPENALEX_API, params=params, timeout=float(timeout))
        payload = response.json()
        records = []
        for item in payload.get("results", []) if isinstance(payload, dict) else []:
            if not isinstance(item, dict):
                continue
            url = _valid_result_url(item.get("doi")) or _valid_result_url(item.get("id"))
            title = re.sub(r"\s+", " ", str(item.get("title") or "")).strip()
            if not url or not title:
                continue
            authors = [str((entry.get("author") or {}).get("display_name") or "")
                       for entry in item.get("authorships", []) if isinstance(entry, dict)]
            records.append({
                "source": "openalex", "source_id": str(item.get("id") or ""),
                "title": title, "content": _abstract_from_inverted_index(item.get("abstract_inverted_index")),
                "url": url, "publication_date": item.get("publication_date"),
                "publication_year": item.get("publication_year"), "authors": authors[:30],
                "document_type": str(item.get("type") or "scholarly_work"),
                "open_access": (item.get("open_access") or {}).get("is_oa"),
                "verification_status": "provider_metadata", "retrieved_at": _now(),
                "license": "OpenAlex bibliographic metadata; abstract and full-text rights may belong to third parties.",
                "attribution": "OpenAlex record and original work; cite the linked DOI/OpenAlex record.",
            })
        return records
    finally:
        if owns_client:
            await http.aclose()


async def search_academic_sources(query: str, *, limit: int = 5, timeout: float = 10.0,
                                 client: Any = None) -> dict[str, Any]:
    """Query both adapters with bounded fan-out and per-provider failure reporting."""
    _query(query)
    results = await asyncio.gather(
        search_arxiv(query, limit=limit, timeout=timeout, client=client),
        search_openalex(query, limit=limit, timeout=timeout, client=client),
        return_exceptions=True,
    )
    records: list[dict[str, Any]] = []
    status: dict[str, str] = {}
    for name, result in zip(("arxiv", "openalex"), results):
        if isinstance(result, BaseException):
            status[name] = "unavailable"
        else:
            status[name] = "ok" if result else "no_results"
            records.extend(result)
    seen: set[tuple[str, str]] = set()
    unique = []
    for record in records:
        identity = (record["source"], str(record.get("source_id") or record["url"]))
        if identity in seen:
            continue
        seen.add(identity)
        unique.append(record)
    return {"query": _query(query), "providers": status, "results": unique}
