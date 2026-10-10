"""ARIA unified local knowledge acquisition, caching, and idle news collector.

Answers should be retrieved from local storage. Network access in this module is
used only for deliberate dataset acquisition and scheduled RSS ingestion; the
ordinary KnowledgeManager query path must not fetch APIs.

Examples:
  python -m brain.knowledge.knowledge_hub sources
  python -m brain.knowledge.knowledge_hub stats
  python -m brain.knowledge.knowledge_hub download wikipedia --destination data/downloads/enwiki.xml.bz2 --max-gb 30
  python -m brain.knowledge.knowledge_hub import-wikipedia --dump data/downloads/enwiki.xml.bz2 --limit 10000
  python -m brain.knowledge.knowledge_hub import-wikidata --dump data/downloads/wikidata.json.bz2 --limit 10000
  python -m brain.knowledge.knowledge_hub import-stackexchange --dump data/Posts.xml
  python -m brain.knowledge.knowledge_hub import-html-archive --archive data/python-docs.zip --base-url https://docs.python.org/3/
  python -m brain.knowledge.knowledge_hub collect-news --force

Full Wikipedia/Wikidata dumps are very large. Downloads are explicit, bounded,
resumable, and never triggered automatically by an idle job.
"""
from __future__ import annotations

import argparse
import asyncio
import bz2
import email.utils
import hashlib
import html
from html.parser import HTMLParser
import json
import logging
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone, timedelta
from typing import Any, Iterable

LOG = logging.getLogger("aria.knowledge_hub")
DEFAULT_DB = os.environ.get("ARIA_OPEN_KNOWLEDGE_DB", "data/aria_open_knowledge.sqlite3")
USER_AGENT = os.environ.get("ARIA_KNOWLEDGE_USER_AGENT", "ARIA-KnowledgeBot/1.0 (local-first educational assistant)")
DEFAULT_MAX_DOWNLOAD_GB = float(os.environ.get("ARIA_MAX_DUMP_GB", "2"))
IDLE_SECONDS = max(60, int(os.environ.get("ARIA_KNOWLEDGE_IDLE_SECONDS", "600")))
NEWS_MAX_AGE_DAYS = max(1, int(os.environ.get("ARIA_NEWS_MAX_AGE_DAYS", "14")))
NEWS_PER_FEED = max(1, min(50, int(os.environ.get("ARIA_NEWS_ITEMS_PER_FEED", "20"))))

# RSS is used only for scheduled acquisition, not on-demand answer generation.
DEFAULT_FEEDS = [
    ("bbc_world", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("bbc_technology", "https://feeds.bbci.co.uk/news/technology/rss.xml"),
    ("bbc_science", "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml"),
    ("python_blog", "https://blog.python.org/feeds/posts/default?alt=rss"),
    ("github_changelog", "https://github.blog/changelog/feed/"),
    ("arxiv_ai", "https://export.arxiv.org/rss/cs.AI"),
    ("arxiv_software_engineering", "https://export.arxiv.org/rss/cs.SE"),
    ("hacker_news", "https://hnrss.org/frontpage"),
    ("nasa_news", "https://www.nasa.gov/news-release/feed/"),
]

DATASET_URLS = {
    "wikipedia": "https://dumps.wikimedia.org/enwiki/latest/enwiki-latest-pages-articles.xml.bz2",
    "wikidata": "https://dumps.wikimedia.org/wikidatawiki/entities/latest-all.json.bz2",
}

class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0
    def handle_starttag(self, tag, attrs):
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self._skip += 1
        elif tag.lower() in {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "tr"}:
            self.parts.append(" ")
    def handle_endtag(self, tag):
        if tag.lower() in {"script", "style", "noscript", "svg"} and self._skip:
            self._skip -= 1
        elif tag.lower() in {"p", "div", "li", "h1", "h2", "h3", "h4", "tr"}:
            self.parts.append(" ")
    def handle_data(self, data):
        if not self._skip and data:
            self.parts.append(data)
    def text(self):
        return re.sub(r"\s+", " ", html.unescape(" ".join(self.parts))).strip()

def _extract_text(value: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(str(value or ""))
        return parser.text()
    except Exception:
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(value or ""))).strip()

def _db_path(db_path: str | None = None) -> Path:
    return Path(db_path or os.environ.get("ARIA_OPEN_KNOWLEDGE_DB", DEFAULT_DB)).expanduser()

def _raw_connect(db_path: str | None = None) -> sqlite3.Connection:
    path = _db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=20000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""CREATE TABLE IF NOT EXISTS knowledge_hub_state (
        key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at REAL NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS knowledge_answer_cache (
        question_hash TEXT PRIMARY KEY, normalized_question TEXT NOT NULL,
        question TEXT NOT NULL, answer TEXT NOT NULL, sources_json TEXT NOT NULL,
        created_at REAL NOT NULL, expires_at REAL NOT NULL, hit_count INTEGER NOT NULL DEFAULT 0,
        last_accessed REAL NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS knowledge_active_requests (
        request_id TEXT PRIMARY KEY, started_at REAL NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS knowledge_feed_state (
        feed_url TEXT PRIMARY KEY, feed_name TEXT NOT NULL, last_checked REAL,
        last_success REAL, last_error TEXT, items_stored INTEGER NOT NULL DEFAULT 0
    )""")
    conn.commit()
    return conn

def _normalize_question(question: str) -> str:
    value = re.sub(r"\s+", " ", str(question or "").strip().lower().replace("’", "'"))
    value = re.sub(r"[\s?.!,;:]+$", "", value)
    return value

def _question_hash(question: str) -> str:
    return hashlib.sha256(_normalize_question(question).encode("utf-8")).hexdigest()

def mark_user_activity() -> None:
    """Record a validated incoming user request so background ingestion can wait."""
    conn = _raw_connect()
    try:
        conn.execute(
            "INSERT INTO knowledge_hub_state(key,value,updated_at) VALUES('last_user_activity',?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
            (str(time.time()), time.time()),
        )
        conn.commit()
    finally:
        conn.close()

def begin_user_activity(request_id: str) -> None:
    now = time.time()
    conn = _raw_connect()
    try:
        conn.execute("INSERT OR REPLACE INTO knowledge_active_requests(request_id,started_at) VALUES(?,?)", (str(request_id), now))
        conn.execute(
            "INSERT INTO knowledge_hub_state(key,value,updated_at) VALUES('last_user_activity',?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
            (str(now), now),
        )
        conn.commit()
    finally:
        conn.close()

def end_user_activity(request_id: str) -> None:
    conn = _raw_connect()
    try:
        conn.execute("DELETE FROM knowledge_active_requests WHERE request_id=?", (str(request_id),))
        conn.commit()
    finally:
        conn.close()

def get_cached_answer(question: str) -> dict[str, Any] | None:
    normalized = _normalize_question(question)
    if len(normalized) < 4:
        return None
    conn = _raw_connect()
    try:
        now = time.time()
        row = conn.execute(
            "SELECT question,answer,sources_json,created_at,expires_at FROM knowledge_answer_cache WHERE question_hash=? AND expires_at>?",
            (_question_hash(question), now),
        ).fetchone()
        if not row:
            conn.execute("DELETE FROM knowledge_answer_cache WHERE expires_at<=?", (now,))
            conn.commit()
            return None
        conn.execute(
            "UPDATE knowledge_answer_cache SET hit_count=hit_count+1,last_accessed=? WHERE question_hash=?",
            (now, _question_hash(question)),
        )
        conn.commit()
        try:
            sources = json.loads(row["sources_json"] or "[]")
        except json.JSONDecodeError:
            sources = []
        return {"question": row["question"], "answer": row["answer"], "sources": sources, "created_at": row["created_at"], "expires_at": row["expires_at"]}
    finally:
        conn.close()

def cache_answer(question: str, answer: str, evidence: list[dict[str, Any]] | None = None) -> bool:
    normalized = _normalize_question(question)
    answer = str(answer or "").strip()
    if len(normalized) < 4 or len(answer) < 20:
        return False
    lowered = answer.lower()
    if any(marker in lowered for marker in (
        "couldn't find reliable information", "could not safely compose", "temporarily unable",
        "provider failed", "please try again later", "language models are unavailable",
    )):
        return False
    evidence = evidence or []
    # Cache only evidence-grounded answers, not generic conversation outputs.
    safe_sources = []
    for item in evidence[:12]:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or item.get("source_url") or "").strip()
        source = str(item.get("source") or "").strip()
        title = str(item.get("title") or "").strip()
        if source or url:
            safe_sources.append({"source": source, "title": title, "url": url})
    blocked_sources = {"memory", "conversation", "working_memory", "episodic_memory", "chat", "success", "assistant_response", "llm_response"}
    safe_sources = [item for item in safe_sources if str(item.get("source") or "").lower() not in blocked_sources]
    if not safe_sources:
        return False
    now = time.time()
    # News/current-information answers expire quickly; stable facts are retained longer.
    if re.search(r"\b(news|latest|current|today|breaking|recent)\b", normalized):
        ttl = max(300, int(os.environ.get("ARIA_NEWS_ANSWER_CACHE_SECONDS", "1200")))
    else:
        ttl = max(3600, int(os.environ.get("ARIA_FACT_ANSWER_CACHE_SECONDS", str(30 * 86400))))
    conn = _raw_connect()
    try:
        conn.execute(
            """INSERT INTO knowledge_answer_cache
            (question_hash,normalized_question,question,answer,sources_json,created_at,expires_at,hit_count,last_accessed)
            VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(question_hash) DO UPDATE SET
            normalized_question=excluded.normalized_question, question=excluded.question,
            answer=excluded.answer, sources_json=excluded.sources_json,
            created_at=excluded.created_at, expires_at=excluded.expires_at, last_accessed=excluded.last_accessed""",
            (_question_hash(question), normalized, question[:1000], answer[:50000], json.dumps(safe_sources, ensure_ascii=False), now, now + ttl, 0, now),
        )
        conn.commit()
        return True
    finally:
        conn.close()

def _feed_list() -> list[tuple[str, str]]:
    override = os.environ.get("ARIA_NEWS_FEEDS", "").strip()
    if not override:
        return list(DEFAULT_FEEDS)
    result = []
    for index, raw in enumerate(override.split(";"), 1):
        url = raw.strip()
        if not url.startswith("https://"):
            continue
        parsed = urllib.parse.urlparse(url)
        name = re.sub(r"[^a-z0-9]+", "_", (parsed.netloc + parsed.path).lower()).strip("_")[:60]
        result.append((name or f"custom_feed_{index}", url))
    return result or list(DEFAULT_FEEDS)

def _local_name(tag: str) -> str:
    return str(tag).rsplit("}", 1)[-1].lower()

def _entry_child(entry: ET.Element, names: set[str]) -> str:
    for child in list(entry):
        if _local_name(child.tag) in names:
            if _local_name(child.tag) == "link":
                href = child.attrib.get("href")
                if href:
                    return href.strip()
            text = " ".join(child.itertext()).strip()
            if text:
                return text
    return ""

def _parse_date(value: str) -> datetime | None:
    value = str(value or "").strip()
    if not value:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        pass
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None

def _fetch_feed(feed_name: str, url: str, timeout: float = 12.0) -> list[dict[str, Any]]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.8"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read(3_000_001)
    if len(payload) > 3_000_000:
        payload = payload[:3_000_000]
    root = ET.fromstring(payload)
    entries = [node for node in root.iter() if _local_name(node.tag) in {"item", "entry"}]
    cutoff = datetime.now(timezone.utc) - timedelta(days=NEWS_MAX_AGE_DAYS)
    records = []
    for entry in entries[:NEWS_PER_FEED * 2]:
        title = _entry_child(entry, {"title"})
        link = _entry_child(entry, {"link", "id"})
        if not link or not link.startswith(("https://", "http://")):
            guid = _entry_child(entry, {"guid", "id"})
            link = guid if guid.startswith(("https://", "http://")) else ""
        if not title or not link:
            continue
        summary = _entry_child(entry, {"description", "summary", "content", "encoded", "subtitle"})
        summary = _extract_text(summary)[:6000]
        published_raw = _entry_child(entry, {"pubdate", "published", "updated", "date"})
        published = _parse_date(published_raw)
        if published and published < cutoff:
            continue
        published_text = published.isoformat() if published else "Unknown publication date"
        content = f"Published: {published_text}\nFeed: {feed_name}\nHeadline: {title.strip()}"
        if summary:
            content += f"\nSummary: {summary}"
        records.append({"source": "news", "source_id": link[:300], "title": title.strip()[:500], "content": content[:12000], "url": link[:2000], "language": "en"})
        if len(records) >= NEWS_PER_FEED:
            break
    return records

def collect_news_and_updates(force: bool = False, db_path: str | None = None) -> dict[str, Any]:
    """Acquire recent headlines/summaries from configured RSS feeds into SQLite."""
    from brain.knowledge.open_knowledge import import_records
    conn = _raw_connect(db_path)
    try:
        feeds = _feed_list()
        all_records: list[dict[str, Any]] = []
        outcomes = []
        for feed_name, feed_url in feeds:
            now = time.time()
            try:
                records = _fetch_feed(feed_name, feed_url)
                all_records.extend(records)
                conn.execute(
                    """INSERT INTO knowledge_feed_state(feed_url,feed_name,last_checked,last_success,last_error,items_stored)
                    VALUES(?,?,?,?,NULL,?) ON CONFLICT(feed_url) DO UPDATE SET feed_name=excluded.feed_name,
                    last_checked=excluded.last_checked,last_success=excluded.last_success,last_error=NULL,
                    items_stored=excluded.items_stored""",
                    (feed_url, feed_name, now, now, len(records)),
                )
                outcomes.append({"feed": feed_name, "items": len(records), "status": "ok"})
            except Exception as exc:
                conn.execute(
                    """INSERT INTO knowledge_feed_state(feed_url,feed_name,last_checked,last_success,last_error,items_stored)
                    VALUES(?,?,?,NULL,?,0) ON CONFLICT(feed_url) DO UPDATE SET feed_name=excluded.feed_name,
                    last_checked=excluded.last_checked,last_error=excluded.last_error""",
                    (feed_url, feed_name, now, str(exc)[:1000]),
                )
                outcomes.append({"feed": feed_name, "items": 0, "status": "error", "error": str(exc)[:240]})
                LOG.warning("[KnowledgeHub] RSS feed %s failed: %s", feed_name, exc)
        conn.commit()
    finally:
        conn.close()
    if all_records:
        result = import_records(str(_db_path(db_path)), all_records, batch_size=100)
    else:
        result = {"processed": 0, "database": str(_db_path(db_path).resolve())}
    summary = {"feeds_checked": len(outcomes), "items_seen": len(all_records), "import": result, "feeds": outcomes}
    LOG.info("[KnowledgeHub] RSS acquisition finished | feeds=%d items=%d", len(outcomes), len(all_records))
    return summary

def collect_news_if_idle(db_path: str | None = None) -> dict[str, Any]:
    conn = _raw_connect(db_path)
    try:
        now = time.time()
        row = conn.execute("SELECT value FROM knowledge_hub_state WHERE key='last_user_activity'").fetchone()
        last_activity = float(row[0]) if row and str(row[0]).replace('.', '', 1).isdigit() else 0.0
        # Ignore stale request markers after a process crash, but never collect during a live request.
        conn.execute("DELETE FROM knowledge_active_requests WHERE started_at<?", (now - 7200,))
        active = conn.execute("SELECT COUNT(*) FROM knowledge_active_requests WHERE started_at>=?", (now - 7200,)).fetchone()[0]
        conn.commit()
    finally:
        conn.close()
    quiet_for = now - last_activity
    if active:
        return {"status": "skipped_active_requests", "active_requests": active}
    if last_activity and quiet_for < IDLE_SECONDS:
        return {"status": "skipped_not_idle", "quiet_seconds": int(quiet_for), "required_seconds": IDLE_SECONDS}
    return collect_news_and_updates(db_path=db_path)

async def idle_knowledge_collection() -> dict[str, Any]:
    """Scheduler entry point. Run network ingestion off the asyncio event loop."""
    return await asyncio.to_thread(collect_news_if_idle)

def _download_url(url: str, destination: str, max_gb: float, timeout: float = 30.0) -> dict[str, Any]:
    if not url.startswith("https://"):
        raise ValueError("Dataset downloads must use HTTPS")
    dest = Path(destination).expanduser()
    dest.parent.mkdir(parents=True, exist_ok=True)
    max_bytes = int(max_gb * (1024 ** 3))
    if max_bytes <= 0:
        raise ValueError("max_gb must be positive")
    free = shutil.disk_usage(dest.parent).free
    if free < min(max_bytes, 512 * 1024 * 1024):
        raise OSError(f"Insufficient free disk space in {dest.parent}: {free / 1024**3:.2f} GiB free")
    partial = Path(str(dest) + ".part")
    offset = partial.stat().st_size if partial.exists() else 0
    headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        status = getattr(response, "status", 200)
        if offset and status != 206:
            offset = 0
        content_length = response.headers.get("Content-Length")
        expected = (offset + int(content_length)) if content_length and str(content_length).isdigit() else None
        if expected and expected > max_bytes:
            raise OSError(f"Dataset is {expected / 1024**3:.2f} GiB, above configured max {max_gb:.2f} GiB. Increase --max-gb only after provisioning enough persistent storage.")
        if expected and expected > free:
            raise OSError(f"Dataset needs about {expected / 1024**3:.2f} GiB but only {free / 1024**3:.2f} GiB is free")
        mode = "ab" if offset and status == 206 else "wb"
        downloaded = offset if mode == "ab" else 0
        with open(partial, mode) as out:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                downloaded += len(chunk)
                if downloaded > max_bytes:
                    raise OSError(f"Download exceeded --max-gb={max_gb:.2f}; partial file retained for safe resume")
                out.write(chunk)
            out.flush()
            os.fsync(out.fileno())
    partial.replace(dest)
    return {"url": url, "path": str(dest.resolve()), "bytes": dest.stat().st_size, "size_gib": round(dest.stat().st_size / (1024**3), 3)}

def download_dataset(name: str, destination: str, max_gb: float = DEFAULT_MAX_DOWNLOAD_GB, url: str | None = None) -> dict[str, Any]:
    name = name.lower().strip()
    if url:
        return _download_url(url, destination, max_gb)
    if name not in DATASET_URLS:
        raise ValueError(f"Unknown dataset {name!r}; use wikipedia or wikidata, or pass --url")
    primary = DATASET_URLS[name]
    candidates = [primary]
    if name == "wikidata":
        candidates.append("https://dumps.wikimedia.org/wikidatawiki/entities/latest-all.json.gz")
    last_error = None
    for candidate in candidates:
        try:
            return _download_url(candidate, destination, max_gb)
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code in (403, 404):
                continue
            raise
    raise OSError(f"No official dump URL succeeded: {last_error}")

def import_stackexchange_posts(dump_path: str, db_path: str | None = None, limit: int | None = None, batch_size: int = 250) -> dict[str, Any]:
    """Import an extracted Stack Exchange Posts.xml file; answers/questions are stored separately."""
    from brain.knowledge.open_knowledge import import_records, open_text, local_name
    def records():
        processed = 0
        with open_text(dump_path) as stream:
            for _, elem in ET.iterparse(stream, events=("end",)):
                if local_name(elem.tag).lower() != "row":
                    continue
                attrs = elem.attrib
                post_id = attrs.get("Id", "")
                body = _extract_text(attrs.get("Body", ""))
                title = _extract_text(attrs.get("Title", ""))
                if not post_id or not body:
                    elem.clear(); continue
                tags = re.sub(r"><", ", ", attrs.get("Tags", "").strip("<>"))
                post_type = attrs.get("PostTypeId", "")
                parent_id = attrs.get("ParentId", "")
                label = title or ("Stack Exchange answer" if post_type == "2" else "Stack Exchange post")
                content = f"{label}\nTags: {tags}\nScore: {attrs.get('Score','0')}\n{body}"
                question_id = parent_id or post_id
                yield {"source": "stackoverflow_dump", "source_id": post_id, "title": label[:500], "content": content[:100000], "url": f"https://stackoverflow.com/questions/{question_id}", "language": "en"}
                processed += 1
                elem.clear()
                if limit is not None and processed >= limit:
                    break
    return import_records(str(_db_path(db_path)), records(), limit=limit, batch_size=batch_size)

def import_html_archive(archive_path: str, db_path: str | None = None, base_url: str = "https://docs.python.org/3/", limit: int | None = None, max_file_mb: int = 8) -> dict[str, Any]:
    """Import HTML/Markdown/text pages from an offline documentation ZIP."""
    from brain.knowledge.open_knowledge import import_records
    base_url = base_url.rstrip("/") + "/"
    def records():
        with zipfile.ZipFile(archive_path) as archive:
            processed = 0
            names = [name for name in archive.namelist() if not name.endswith("/") and PurePosixPath(name).suffix.lower() in {".html", ".htm", ".md", ".txt"}]
            for name in names:
                info = archive.getinfo(name)
                if info.file_size > max_file_mb * 1024 * 1024:
                    continue
                try:
                    raw = archive.read(name).decode("utf-8", errors="replace")
                except Exception:
                    continue
                if name.lower().endswith((".html", ".htm")):
                    title_match = re.search(r"(?is)<title[^>]*>(.*?)</title>", raw)
                    title = _extract_text(title_match.group(1)) if title_match else PurePosixPath(name).stem.replace("_", " ")
                    content = _extract_text(raw)
                else:
                    title = PurePosixPath(name).stem.replace("_", " ")
                    content = re.sub(r"\s+", " ", raw).strip()
                if len(content) < 80:
                    continue
                parts = PurePosixPath(name).parts
                if parts and re.match(r".*docs.*", parts[0], re.I):
                    rel = "/".join(parts[1:])
                else:
                    rel = name
                yield {"source": "official_documentation", "source_id": name, "title": title[:500], "content": content[:100000], "url": urllib.parse.urljoin(base_url, urllib.parse.quote(rel, safe="/._-#")), "language": "en"}
                processed += 1
                if limit is not None and processed >= limit:
                    break
    return import_records(str(_db_path(db_path)), records(), limit=limit, batch_size=100)

def source_catalog() -> list[dict[str, str]]:
    return [
        {"name": "Wikipedia", "method": "official compressed XML dump", "command": "download wikipedia, then import-wikipedia"},
        {"name": "Wikidata", "method": "official compressed entity dump", "command": "download wikidata, then import-wikidata"},
        {"name": "Stack Exchange / Stack Overflow", "method": "download/extract official data dump; import Posts.xml", "command": "import-stackexchange"},
        {"name": "Official programming documentation", "method": "offline HTML/Markdown ZIP archive", "command": "import-html-archive"},
        {"name": "Recent news, science and coding updates", "method": "scheduled RSS feed acquisition; stored locally", "command": "collect-news"},
        {"name": "Other open datasets", "method": "custom HTTPS download plus supported importer/source adapter", "command": "download --url ..."},
    ]

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ARIA local knowledge hub")
    sub = parser.add_subparsers(dest="command", required=True)
    src = sub.add_parser("sources");
    stats = sub.add_parser("stats"); stats.add_argument("--db", default=DEFAULT_DB)
    dl = sub.add_parser("download", help="Explicitly download an official dump or custom HTTPS dataset")
    dl.add_argument("dataset", choices=["wikipedia", "wikidata", "custom"])
    dl.add_argument("--destination", required=True); dl.add_argument("--max-gb", type=float, default=DEFAULT_MAX_DOWNLOAD_GB); dl.add_argument("--url")
    wi = sub.add_parser("import-wikipedia"); wi.add_argument("--dump", required=True); wi.add_argument("--db", default=DEFAULT_DB); wi.add_argument("--language", default="en"); wi.add_argument("--limit", type=int); wi.add_argument("--batch-size", type=int, default=250)
    wd = sub.add_parser("import-wikidata"); wd.add_argument("--dump", required=True); wd.add_argument("--db", default=DEFAULT_DB); wd.add_argument("--limit", type=int); wd.add_argument("--batch-size", type=int, default=250)
    se = sub.add_parser("import-stackexchange"); se.add_argument("--dump", required=True); se.add_argument("--db", default=DEFAULT_DB); se.add_argument("--limit", type=int); se.add_argument("--batch-size", type=int, default=250)
    doc = sub.add_parser("import-html-archive"); doc.add_argument("--archive", required=True); doc.add_argument("--db", default=DEFAULT_DB); doc.add_argument("--base-url", default="https://docs.python.org/3/"); doc.add_argument("--limit", type=int); doc.add_argument("--max-file-mb", type=int, default=8)
    news = sub.add_parser("collect-news"); news.add_argument("--db", default=DEFAULT_DB); news.add_argument("--force", action="store_true")
    return parser

def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = build_parser().parse_args(argv)
    try:
        if args.command == "sources":
            result = source_catalog()
        elif args.command == "download":
            result = download_dataset(args.dataset, args.destination, args.max_gb, args.url)
        elif args.command == "import-wikipedia":
            from brain.knowledge.open_knowledge import wikipedia_pages, import_records
            result = import_records(args.db, wikipedia_pages(args.dump, args.language), args.limit, args.batch_size)
        elif args.command == "import-wikidata":
            from brain.knowledge.open_knowledge import wikidata_entities, import_records
            result = import_records(args.db, wikidata_entities(args.dump), args.limit, args.batch_size)
        elif args.command == "import-stackexchange":
            result = import_stackexchange_posts(args.dump, args.db, args.limit, args.batch_size)
        elif args.command == "import-html-archive":
            result = import_html_archive(args.archive, args.db, args.base_url, args.limit, args.max_file_mb)
        elif args.command == "collect-news":
            result = collect_news_and_updates(force=args.force, db_path=args.db)
        elif args.command == "stats":
            from brain.knowledge.open_knowledge import connect
            conn = connect(args.db)
            try:
                counts = {row[0]: row[1] for row in conn.execute("SELECT source,COUNT(*) FROM documents GROUP BY source")}
                total = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            finally:
                conn.close()
            hub = _raw_connect(args.db)
            try:
                cache_count = hub.execute("SELECT COUNT(*) FROM knowledge_answer_cache WHERE expires_at>?", (time.time(),)).fetchone()[0]
                feeds = [dict(row) for row in hub.execute("SELECT feed_name,last_success,last_error,items_stored FROM knowledge_feed_state ORDER BY feed_name")]
            finally:
                hub.close()
            result = {"database": str(_db_path(args.db).resolve()), "total_documents": total, "documents_by_source": counts, "cached_answers": cache_count, "feeds": feeds}
        else:
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        LOG.exception("[KnowledgeHub] Operation failed: %s", exc)
        return 1

if __name__ == "__main__":
    sys.exit(main())
