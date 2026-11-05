from __future__ import annotations

import json
import os
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from brain.knowledge.embedder import sync_file_to_vector_db

_OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
_OPEN_METEO_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
_OPEN_LIBRARY_SEARCH_URL = "https://openlibrary.org/search.json"
_OPEN_ALEX_WORKS_URL = "https://api.openalex.org/works"
_WIKIPEDIA_SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary"
_OPEN_NOTIFY_ASTROS_URL = "http://api.open-notify.org/astros.json"

KNOWLEDGE_DIR = Path("data/knowledge")


def save_knowledge_record(category: str, key_name: str, payload: Dict[str, Any]) -> str:
    """Save knowledge payload to data/knowledge/<category>/<key_name>.json and sync to ChromaDB."""
    try:
        target_dir = KNOWLEDGE_DIR / category
        target_dir.mkdir(parents=True, exist_ok=True)

        clean_filename = "".join(c if c.isalnum() or c in (" ", "_") else "" for c in key_name).strip()
        filename = f"{clean_filename.lower().replace(' ', '_')[:60]}.json"
        file_path = target_dir / filename

        data_to_write = {
            "category": category,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "data": payload
        }

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data_to_write, f, indent=2)

        # Trigger auto-vectorization
        sync_file_to_vector_db(str(file_path))

        return str(file_path)
    except Exception as e:
        print(f"[KnowledgeStorage Error]: {e}")
        return ""


async def _get_json(url: str, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None) -> Any:
    req_headers = {"User-Agent": "ARIA-AI-Platform/2.0 (mailto:saketh@aria.internal)"}
    if headers:
        req_headers.update(headers)

    async with httpx.AsyncClient(timeout=10.0, headers=req_headers, follow_redirects=True) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


async def get_wikipedia_summary(topic: str, save_to_disk: bool = True) -> Dict[str, Any]:
    try:
        encoded_topic = urllib.parse.quote(topic.strip().replace(" ", "_"))
        url = f"{_WIKIPEDIA_SUMMARY_URL}/{encoded_topic}"
        data = await _get_json(url)

        summary = {
            "title": data.get("title"),
            "description": data.get("description"),
            "extract": data.get("extract"),
            "url": data.get("content_urls", {}).get("desktop", {}).get("page")
        }
        if save_to_disk and summary.get("title"):
            summary["saved_path"] = save_knowledge_record("wikipedia", topic, summary)
        return summary
    except Exception as e:
        return {"topic": topic, "error": str(e)}


async def get_weather(city: str = "Visakhapatnam", save_to_disk: bool = True) -> Dict[str, Any]:
    latitude, longitude = 17.6868, 83.2185
    try:
        geo = await _get_json(
            _OPEN_METEO_GEOCODE_URL,
            params={"name": city, "count": 1, "language": "en", "format": "json"},
        )
        results = geo.get("results")
        if results:
            latitude = results[0]["latitude"]
            longitude = results[0]["longitude"]
    except Exception:
        pass

    try:
        data = await _get_json(
            _OPEN_METEO_URL,
            params={"latitude": latitude, "longitude": longitude, "current_weather": "true"},
        )
        current = data.get("current_weather", {})
        summary = {
            "city": city,
            "temperature_c": current.get("temperature"),
            "wind_speed_kph": current.get("windspeed"),
            "weather_code": current.get("weathercode"),
            "time": current.get("time"),
        }
        if save_to_disk:
            summary["saved_path"] = save_knowledge_record("weather", city, summary)
        return summary
    except Exception as e:
        return {"city": city, "error": str(e)}


async def get_book_info(title: str, save_to_disk: bool = True) -> Optional[Dict[str, Any]]:
    try:
        query = urllib.parse.quote(title)
        url = f"{_OPEN_LIBRARY_SEARCH_URL}?q={query}&limit=1"
        data = await _get_json(url)

        docs: List[Dict[str, Any]] = data.get("docs", [])
        if not docs:
            return None

        doc = docs[0]
        summary = {
            "title": doc.get("title"),
            "author_name": doc.get("author_name"),
            "first_publish_year": doc.get("first_publish_year"),
            "openlibrary_key": doc.get("key"),
            "isbn": (doc.get("isbn") or [None])[0],
        }

        if save_to_disk and summary.get("title"):
            summary["saved_path"] = save_knowledge_record("books", title, summary)
        return summary
    except Exception as e:
        return {"title": title, "error": str(e)}


async def get_academic_paper(topic: str, save_to_disk: bool = True) -> Optional[Dict[str, Any]]:
    try:
        data = await _get_json(_OPEN_ALEX_WORKS_URL, params={"search": topic, "per_page": 1})
        results: List[Dict[str, Any]] = data.get("results", [])
        if not results:
            return None

        work = results[0]
        authors = [auth.get("author", {}).get("display_name") for auth in work.get("authorships", [])]
        summary = {
            "doi": work.get("doi"),
            "title": work.get("title"),
            "authors": authors,
            "year": work.get("publication_year"),
            "venue": work.get("host_venue", {}).get("display_name"),
            "openalex_url": work.get("id"),
        }
        if save_to_disk:
            summary["saved_path"] = save_knowledge_record("science", topic, summary)
        return summary
    except Exception as e:
        return {"topic": topic, "error": str(e)}


async def get_space_info(save_to_disk: bool = True) -> Dict[str, Any]:
    try:
        data = await _get_json(_OPEN_NOTIFY_ASTROS_URL)
        summary = {
            "number_in_space": data.get("number", 0),
            "astronauts": [p.get("name") for p in data.get("people", [])],
            "fetched_at": datetime.now(timezone.utc).isoformat()
        }
        if save_to_disk:
            summary["saved_path"] = save_knowledge_record("space", "astronauts_in_space", summary)
        return summary
    except Exception as e:
        return {"error": str(e)}


async def get_ip_info(target: str = "8.8.8.8", save_to_disk: bool = True) -> Dict[str, Any]:
    """Keyless IP Geolocation & ASN metadata lookup."""
    try:
        url = f"http://ip-api.com/json/{target}"
        data = await _get_json(url)
        summary = {
            "target": target,
            "status": data.get("status"),
            "country": data.get("country"),
            "city": data.get("city"),
            "isp": data.get("isp"),
            "org": data.get("org"),
            "as": data.get("as"),
            "lat": data.get("lat"),
            "lon": data.get("lon")
        }
        if save_to_disk and summary.get("status") == "success":
            summary["saved_path"] = save_knowledge_record("network_ip", target, summary)
        return summary
    except Exception as e:
        return {"target": target, "error": str(e)}


async def get_dns_records(domain: str = "example.com", save_to_disk: bool = True) -> Dict[str, Any]:
    """Keyless DNS lookup via Cloudflare DNS-over-HTTPS."""
    try:
        url = f"https://cloudflare-dns.com/dns-query?name={domain}&type=A"
        data = await _get_json(url, headers={"Accept": "application/dns-json"})
        records = [ans.get("data") for ans in data.get("Answer", [])]
        summary = {"domain": domain, "a_records": records}
        if save_to_disk:
            summary["saved_path"] = save_knowledge_record("network_dns", domain, summary)
        return summary
    except Exception as e:
        return {"domain": domain, "error": str(e)}
