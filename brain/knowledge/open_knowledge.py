
"""ARIA local open-knowledge importer.

Supports Wikipedia XML dumps and Wikidata JSON-lines dumps.
Uses SQLite, supports compressed .bz2/.gz inputs, resumable imports,
deduplication, source URLs, full-text search when FTS5 is available,
and a LIKE fallback otherwise.

Examples:
  python -m brain.knowledge.open_knowledge init --db data/aria_knowledge.sqlite3
  python -m brain.knowledge.open_knowledge wikipedia --dump data/wiki.xml.bz2 --db data/aria_knowledge.sqlite3 --limit 1000
  python -m brain.knowledge.open_knowledge wikidata --dump data/wikidata.json.bz2 --db data/aria_knowledge.sqlite3 --limit 1000
  python -m brain.knowledge.open_knowledge import-both --wikipedia-dump data/wiki.xml.bz2 --wikidata-dump data/wikidata.json.bz2 --db data/aria_knowledge.sqlite3
  python -m brain.knowledge.open_knowledge search --db data/aria_knowledge.sqlite3 --query "photosynthesis"
  python -m brain.knowledge.open_knowledge stats --db data/aria_knowledge.sqlite3
"""

from __future__ import annotations

import argparse
import bz2
import gzip
import json
import logging
import os
import re
import sqlite3
import sys
import time
import xml.etree.ElementTree as ET

from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

LOG = logging.getLogger("aria.open_knowledge")

DEFAULT_DB = os.environ.get(
    "ARIA_OPEN_KNOWLEDGE_DB",
    "data/aria_open_knowledge.sqlite3",
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    url TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'en',
    license TEXT NOT NULL DEFAULT 'unknown',
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source, source_id)
);

CREATE INDEX IF NOT EXISTS idx_documents_source
ON documents(source);

CREATE INDEX IF NOT EXISTS idx_documents_title
ON documents(title);
"""


def connect(db_path: str) -> sqlite3.Connection:
    """Open the local database and create required indexes."""
    path = Path(db_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.executescript(SCHEMA)
    # Upgrade databases created by older ARIA versions without discarding records.
    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(documents)")}
    if "license" not in columns:
        conn.execute("ALTER TABLE documents ADD COLUMN license TEXT NOT NULL DEFAULT 'unknown'")
        conn.commit()

    try:
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts
            USING fts5(
                title,
                content,
                source,
                source_id UNINDEXED,
                content='documents',
                content_rowid='id'
            )
        """)

        conn.executescript("""
            CREATE TRIGGER IF NOT EXISTS documents_ai
            AFTER INSERT ON documents BEGIN
                INSERT INTO documents_fts(
                    rowid, title, content, source, source_id
                )
                VALUES (
                    new.id, new.title, new.content,
                    new.source, new.source_id
                );
            END;

            CREATE TRIGGER IF NOT EXISTS documents_ad
            AFTER DELETE ON documents BEGIN
                INSERT INTO documents_fts(
                    documents_fts, rowid, title,
                    content, source, source_id
                )
                VALUES (
                    'delete', old.id, old.title,
                    old.content, old.source, old.source_id
                );
            END;

            CREATE TRIGGER IF NOT EXISTS documents_au
            AFTER UPDATE ON documents BEGIN
                INSERT INTO documents_fts(
                    documents_fts, rowid, title,
                    content, source, source_id
                )
                VALUES (
                    'delete', old.id, old.title,
                    old.content, old.source, old.source_id
                );

                INSERT INTO documents_fts(
                    rowid, title, content, source, source_id
                )
                VALUES (
                    new.id, new.title, new.content,
                    new.source, new.source_id
                );
            END;
        """)

        # Index documents already present before FTS5 was enabled.
        conn.execute("""
            INSERT INTO documents_fts(
                rowid, title, content, source, source_id
            )
            SELECT d.id, d.title, d.content, d.source, d.source_id
            FROM documents d
            WHERE NOT EXISTS (
                SELECT 1 FROM documents_fts f
                WHERE f.rowid = d.id
            )
        """)

    except sqlite3.OperationalError as exc:
        # SQLite builds without FTS5 can still use LIKE search.
        LOG.info("FTS5 unavailable; using fallback search: %s", exc)

    conn.commit()
    return conn


def open_text(path: str):
    """Open plain, bzip2, or gzip text files."""
    lower = str(path).lower()

    if lower.endswith(".bz2"):
        return bz2.open(
            path, "rt", encoding="utf-8", errors="replace"
        )

    if lower.endswith(".gz"):
        return gzip.open(
            path, "rt", encoding="utf-8", errors="replace"
        )

    return open(
        path, "rt", encoding="utf-8", errors="replace"
    )


def clean_text(value: str) -> str:
    value = str(value or "")
    value = value.replace("\x00", " ")
    return re.sub(r"\s+", " ", value).strip()


def clean_wikitext(value: str) -> str:
    """Convert common MediaWiki markup into searchable plain text."""
    text = str(value or "")
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    text = re.sub(r"<ref\b[^>]*>.*?</ref\s*>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<ref\b[^>]*/\s*>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    # Remove simple/nested templates iteratively without unbounded recursion.
    for _ in range(8):
        updated = re.sub(r"\{\{[^{}]*\}\}", " ", text, flags=re.S)
        if updated == text:
            break
        text = updated
    text = re.sub(r"\[\[(?:File|Image):.*?\]\]", " ", text, flags=re.I | re.S)
    text = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", text)
    text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)
    text = re.sub(r"\[(?:https?://\S+\s+)?([^\]]+)\]", r"\1", text)
    text = re.sub(r"'{2,5}", "", text)
    text = re.sub(r"^\s*=+\s*(.*?)\s*=+\s*$", r"\1", text, flags=re.M)
    text = re.sub(r"\[\[Category:.*?\]\]", " ", text, flags=re.I)
    return clean_text(text)


def local_name(tag: str) -> str:
    """Remove an XML namespace from an element name."""
    return tag.rsplit("}", 1)[-1]


def wikipedia_pages(dump_path: str, language: str = "en"):
    """Stream namespace-zero pages from a Wikipedia XML dump."""
    with open_text(dump_path) as stream:
        try:
            for _, elem in ET.iterparse(stream, events=("end",)):
                if local_name(elem.tag) != "page":
                    continue

                title = ""
                page_id = ""
                namespace = "0"
                text = ""
                is_redirect = False

                for child in elem:
                    name = local_name(child.tag)

                    if name == "title":
                        title = child.text or ""

                    elif name == "ns":
                        namespace = child.text or "0"

                    elif name == "id" and not page_id:
                        page_id = child.text or ""

                    elif name == "redirect":
                        is_redirect = True

                    elif name == "revision":
                        for sub in child.iter():
                            if local_name(sub.tag) == "text":
                                text = sub.text or ""

                if (
                    namespace == "0"
                    and title
                    and page_id
                    and text
                    and not is_redirect
                ):
                    yield {
                        "source": "wikipedia",
                        "source_id": page_id,
                        "title": clean_text(title),
                        "content": clean_wikitext(text),
                        "url": (
                            f"https://{language}.wikipedia.org/wiki/"
                            + quote(
                                title.replace(" ", "_"),
                                safe="()'!*~.-_",
                            )
                        ),
                        "language": language,
                    }

                # Release XML memory after processing each page.
                elem.clear()

        except ET.ParseError as exc:
            raise ValueError(
                f"Invalid or incomplete Wikipedia XML: {exc}"
            ) from exc


def wikidata_entities(dump_path: str):
    """Read Wikidata entities from a JSON-lines dump."""
    with open_text(dump_path) as stream:
        for line_no, line in enumerate(stream, start=1):
            line = line.strip()

            if not line or line in {"[", "]", ","}:
                continue

            if line.endswith(","):
                line = line[:-1]

            try:
                entity = json.loads(line)
            except json.JSONDecodeError as exc:
                LOG.warning(
                    "Skipping invalid JSON at line %d: %s",
                    line_no,
                    exc,
                )
                continue

            if not isinstance(entity, dict):
                continue

            entity_id = str(entity.get("id") or "").strip()
            if not entity_id:
                continue

            labels = entity.get("labels") or {}
            descriptions = entity.get("descriptions") or {}

            label = labels.get("en") or next(
                iter(labels.values()), {}
            )
            description = descriptions.get("en") or next(
                iter(descriptions.values()), {}
            )

            title = clean_text(
                (label or {}).get("value") or entity_id
            )

            description_text = clean_text(
                (description or {}).get("value") or ""
            )

            aliases = []
            english_aliases = (
                (entity.get("aliases") or {}).get("en", [])
            )

            for alias in english_aliases[:20]:
                if isinstance(alias, dict) and alias.get("value"):
                    aliases.append(clean_text(alias["value"]))

            claim_summaries = []
            claims = entity.get("claims") or {}

            for prop, statements in list(claims.items())[:40]:
                for statement in (statements or [])[:3]:
                    mainsnak = statement.get("mainsnak") or {}
                    datavalue = mainsnak.get("datavalue") or {}
                    value = datavalue.get("value")

                    if isinstance(value, dict):
                        value = (
                            value.get("id")
                            or value.get("text")
                            or value.get("time")
                            or value.get("amount")
                        )

                    if isinstance(value, (str, int, float)):
                        claim_summaries.append(
                            f"{prop}: {str(value)[:160]}"
                        )

            parts = []

            if description_text:
                parts.append(description_text)

            if aliases:
                parts.append("Aliases: " + ", ".join(aliases))

            if claim_summaries:
                parts.append(
                    "Claims: " + "; ".join(claim_summaries)
                )

            content = clean_text(". ".join(parts))[:12000]

            if not content:
                content = title

            yield {
                "source": "wikidata",
                "source_id": entity_id,
                "title": title,
                "content": content,
                "url": f"https://www.wikidata.org/wiki/{entity_id}",
                "language": "en",
            }


def fetch_and_store_topic(
    db_path: str,
    topic: str,
    language: str = "en",
    timeout: int = 8,
) -> dict:
    """Fetch one topic from official Wikimedia APIs and cache both sources locally.

    This uses encyclopedia/data APIs, not an LLM. It is intentionally a small,
    incremental bootstrap path; bulk dumps remain the way to import large corpora.
    """
    topic = clean_text(topic)[:180]
    if not topic:
        return {"stored": 0, "reason": "empty_topic"}

    def get_json(url: str) -> dict:
        request = Request(
            url,
            headers={
                "User-Agent": "ARIA-OpenKnowledge/1.0 (local knowledge importer)",
                "Accept": "application/json",
            },
        )
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))

    records = []
    page_title = topic.replace(" ", "_")
    wiki_url = (
        f"https://{language}.wikipedia.org/api/rest_v1/page/summary/"
        + quote(page_title, safe="()'!*~.-_")
    )
    try:
        summary = get_json(wiki_url)
        extract = clean_text(summary.get("extract") or "")
        title = clean_text(summary.get("title") or topic)
        page_url = (
            (summary.get("content_urls") or {}).get("desktop") or {}
        ).get("page") or (
            f"https://{language}.wikipedia.org/wiki/"
            + quote(title.replace(" ", "_"), safe="()'!*~.-_")
        )
        if extract and str(summary.get("type") or "").lower() != "disambiguation":
            records.append({
                "source": "wikipedia",
                "source_id": str(summary.get("pageid") or title),
                "title": title,
                "content": extract,
                "url": page_url,
                "language": language,
            })
    except Exception as exc:
        LOG.warning("Wikipedia topic fetch failed for %r: %s", topic, exc)

    try:
        search_url = (
            "https://www.wikidata.org/w/api.php?action=wbsearchentities"
            "&format=json&language=en&uselang=en&limit=1&search="
            + quote(topic, safe="")
        )
        search_data = get_json(search_url)
        entities = search_data.get("search") or []
        if entities:
            found = entities[0]
            qid = clean_text(found.get("id") or "")
            if qid:
                entity_data = get_json(
                    f"https://www.wikidata.org/wiki/Special:EntityData/{quote(qid)}.json"
                )
                entity = (entity_data.get("entities") or {}).get(qid) or {}
                labels = entity.get("labels") or {}
                descriptions = entity.get("descriptions") or {}
                aliases_map = entity.get("aliases") or {}
                label = clean_text(
                    ((labels.get("en") or {}).get("value"))
                    or found.get("label")
                    or qid
                )
                description = clean_text(
                    ((descriptions.get("en") or {}).get("value"))
                    or found.get("description")
                    or ""
                )
                aliases = [
                    clean_text(item.get("value"))
                    for item in aliases_map.get("en", [])[:12]
                    if isinstance(item, dict) and item.get("value")
                ]
                parts = [description] if description else []
                if aliases:
                    parts.append("Aliases: " + ", ".join(aliases))
                content = clean_text(". ".join(parts)) or label
                records.append({
                    "source": "wikidata",
                    "source_id": qid,
                    "title": label,
                    "content": content,
                    "url": f"https://www.wikidata.org/wiki/{qid}",
                    "language": "en",
                })
    except Exception as exc:
        LOG.warning("Wikidata topic fetch failed for %r: %s", topic, exc)

    if not records:
        return {"stored": 0, "reason": "no_wikimedia_records", "topic": topic}

    result = import_records(db_path, records, limit=None, batch_size=50)
    result["topic"] = topic
    result["sources"] = [item["source"] for item in records]
    return result


def import_records(
    db_path: str,
    records,
    limit: int | None = None,
    batch_size: int = 250,
) -> dict:
    """Import records in batches; reruns update the same source IDs."""
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")

    if limit is not None and limit < 0:
        raise ValueError("limit must be zero or greater")

    conn = connect(db_path)
    processed = 0
    changed = 0
    batch = []

    sql = """
        INSERT INTO documents(
            source, source_id, title, content, url, language, license
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source, source_id) DO UPDATE SET
            title=excluded.title,
            content=excluded.content,
            url=excluded.url,
            language=excluded.language,
            license=excluded.license
    """

    try:
        for record in records:
            if limit is not None and processed >= limit:
                break

            title = clean_text(record.get("title"))[:500]
            content = clean_text(record.get("content"))[:1_000_000]
            source_id = clean_text(record.get("source_id"))[:300]
            source = clean_text(record.get("source") or "unknown")[:50]
            url = clean_text(record.get("url"))[:2000]
            language = clean_text(record.get("language") or "en")[:20]
            default_licenses = {
                "wikipedia": "CC BY-SA / GFDL; verify dump terms",
                "wikidata": "CC0 structured data; verify dump terms",
                "stackexchange": "CC BY-SA; preserve attribution",
                "openstax": "Check individual textbook license",
                "pubmed": "Metadata/abstract rights vary; verify record terms",
                "gutenberg": "Verify public-domain status and notices",
                "openalex": "Verify current OpenAlex snapshot terms",
            }
            license_name = clean_text(
                record.get("license") or default_licenses.get(source, "unknown")
            )[:200]

            if not title or not source_id or not content:
                continue

            batch.append(
                (source, source_id, title, content, url, language, license_name)
            )
            processed += 1

            if len(batch) >= batch_size:
                before = conn.total_changes
                conn.executemany(sql, batch)
                conn.commit()
                changed += conn.total_changes - before
                batch.clear()

                LOG.info(
                    "Processed %d records; database changes: %d",
                    processed,
                    changed,
                )

        if batch:
            before = conn.total_changes
            conn.executemany(sql, batch)
            conn.commit()
            changed += conn.total_changes - before

    finally:
        conn.close()

    return {
        "processed": processed,
        "database_changes_including_index_triggers": changed,
        "database": str(Path(db_path).resolve()),
    }


def search(db_path: str, query: str, limit: int = 5) -> list[dict]:
    """Search the local corpus and return source-backed evidence."""
    query = clean_text(query)

    if not query:
        return []

    limit = max(1, min(int(limit), 50))
    conn = connect(db_path)

    try:
        tokens = re.findall(r"[\w'-]+", query)

        if not tokens:
            return []

        match_query = " AND ".join(
            '"' + token.replace('"', '""') + '"'
            for token in tokens
        )

        try:
            rows = conn.execute(
                """
                SELECT
                    d.source, d.source_id, d.title,
                    d.content, d.url, d.language,
                    bm25(documents_fts) AS score
                FROM documents_fts
                JOIN documents d
                    ON d.id = documents_fts.rowid
                WHERE documents_fts MATCH ?
                ORDER BY score
                LIMIT ?
                """,
                (match_query, limit),
            ).fetchall()

        except sqlite3.OperationalError:
            # Fallback for SQLite installations without working FTS5.
            fallback_tokens = [
                token for token in tokens if len(token) > 1
            ][:8]

            if not fallback_tokens:
                return []

            conditions = " AND ".join(
                "(title LIKE ? OR content LIKE ?)"
                for _ in fallback_tokens
            )

            args = []
            for token in fallback_tokens:
                escaped = (
                    token.replace("\\", "\\\\")
                    .replace("%", "\\%")
                    .replace("_", "\\_")
                )
                args.extend([f"%{escaped}%", f"%{escaped}%"])

            rows = conn.execute(
                f"""
                SELECT source, source_id, title,
                       content, url, language
                FROM documents
                WHERE {conditions}
                LIMIT ?
                """,
                (*args, limit),
            ).fetchall()

        return [dict(row) for row in rows]

    finally:
        conn.close()



# A compact starter corpus. Add more lines to a topics file for broader coverage.
DEFAULT_SEED_TOPICS = [
    "Photosynthesis", "Cellular respiration", "Chlorophyll", "Plant",
    "Ecosystem", "Habitat", "Biosphere", "Food chain", "Evolution",
    "DNA", "RNA", "Cell biology", "Human body", "Solar System",
    "Earth", "Moon", "Sun", "Gravity", "Water", "Climate change",
    "Computer", "Computer science", "Algorithm", "Data structure",
    "Python (programming language)", "Java (programming language)",
    "HTML", "CSS", "JavaScript", "Database", "SQL", "Operating system",
    "Computer network", "Internet", "Transmission Control Protocol",
    "User Datagram Protocol", "HTTP", "DNS", "Artificial intelligence",
    "Machine learning", "Neural network", "Cybersecurity", "Cryptography",
    "Mathematics", "Algebra", "Geometry", "Statistics", "Physics",
    "Chemistry", "Biology", "History", "Geography", "Democracy",
    "Economics", "Renewable energy", "Electricity", "Magnetism",
    "Human brain", "Nutrition", "Exercise", "First aid",
]


def seed_topics(
    db_path: str,
    topics,
    delay: float = 0.25,
    timeout: int = 8,
    limit: int | None = None,
) -> dict:
    """Acquire source-backed article summaries and persist them locally.

    Network access happens only during this explicit ingestion operation, never
    as part of answering a user query. Existing records are skipped to make
    repeated runs idempotent and reduce unnecessary requests.
    """
    conn = connect(db_path)
    try:
        existing = {
            str(row[0]).strip().casefold()
            for row in conn.execute(
                "SELECT title FROM documents WHERE source = 'wikipedia'"
            ).fetchall()
        }
    finally:
        conn.close()

    clean_topics = []
    seen = set()
    for item in topics or []:
        topic = clean_text(item)
        key = topic.casefold()
        if topic and key not in seen:
            seen.add(key)
            clean_topics.append(topic)

    if limit is not None:
        clean_topics = clean_topics[:max(0, int(limit))]

    totals = {
        "status": "completed",
        "database": str(Path(db_path).expanduser().resolve()),
        "requested": len(clean_topics),
        "skipped_existing": 0,
        "stored_records": 0,
        "failed_topics": [],
        "topics": [],
    }

    for index, topic in enumerate(clean_topics, start=1):
        if topic.casefold() in existing:
            totals["skipped_existing"] += 1
            continue

        LOG.info("Seeding topic %d/%d: %s", index, len(clean_topics), topic)
        try:
            result = fetch_and_store_topic(
                db_path=db_path,
                topic=topic,
                language="en",
                timeout=timeout,
            )
        except Exception as exc:
            LOG.warning("Topic acquisition failed for %r: %s", topic, exc)
            result = {"stored": 0, "reason": str(exc)}

        stored = int(result.get("processed") or result.get("stored") or result.get("changed") or 0)
        totals["stored_records"] += stored
        totals["topics"].append({"topic": topic, **result})
        if stored <= 0:
            totals["failed_topics"].append({
                "topic": topic,
                "reason": result.get("reason", "no_records_stored"),
            })
        if delay > 0 and index < len(clean_topics):
            time.sleep(min(float(delay), 5.0))

    # Recount actual records because UPSERT results may report processed rows.
    conn = connect(db_path)
    try:
        totals["total_documents"] = int(
            conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        )
    finally:
        conn.close()
    return totals


def read_topics_file(path: str):
    topics = []
    with open(path, "rt", encoding="utf-8", errors="replace") as stream:
        for line in stream:
            line = line.strip()
            if line and not line.startswith("#"):
                topics.append(line)
    return topics


def build_parser():
    parser = argparse.ArgumentParser(
        description="ARIA local open-knowledge importer"
    )

    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Initialize the database")
    init.add_argument("--db", default=DEFAULT_DB)

    seed = sub.add_parser(
        "seed",
        help="Fetch a small set of free Wikimedia article summaries and store them locally",
    )
    seed.add_argument("--db", default=DEFAULT_DB)
    seed.add_argument("--topics-file", default=None,
                      help="Optional UTF-8 file containing one topic per line")
    seed.add_argument("--limit", type=int, default=None,
                      help="Limit number of topics processed")
    seed.add_argument("--delay", type=float, default=0.25,
                      help="Delay between topics in seconds")
    seed.add_argument("--timeout", type=int, default=8,
                      help="HTTP timeout per request in seconds")

    fetch = sub.add_parser(
        "fetch-topic",
        help="Fetch one named topic now and save it to the local corpus",
    )
    fetch.add_argument("--db", default=DEFAULT_DB)
    fetch.add_argument("--topic", required=True)
    fetch.add_argument("--timeout", type=int, default=8)

    wiki = sub.add_parser(
        "wikipedia", help="Import a Wikipedia XML dump"
    )
    wiki.add_argument("--dump", required=True)
    wiki.add_argument("--db", default=DEFAULT_DB)
    wiki.add_argument("--language", default="en")
    wiki.add_argument("--limit", type=int, default=None)
    wiki.add_argument("--batch-size", type=int, default=250)

    both = sub.add_parser(
        "import-both",
        help="Import Wikipedia and Wikidata dumps into the same SQLite database",
    )
    both.add_argument("--wikipedia-dump", required=True)
    both.add_argument("--wikidata-dump", required=True)
    both.add_argument("--db", default=DEFAULT_DB)
    both.add_argument("--language", default="en")
    both.add_argument("--wikipedia-limit", type=int, default=None)
    both.add_argument("--wikidata-limit", type=int, default=None)
    both.add_argument("--batch-size", type=int, default=250)

    wd = sub.add_parser(
        "wikidata", help="Import a Wikidata JSON-lines dump"
    )
    wd.add_argument("--dump", required=True)
    wd.add_argument("--db", default=DEFAULT_DB)
    wd.add_argument("--limit", type=int, default=None)
    wd.add_argument("--batch-size", type=int, default=250)

    srch = sub.add_parser("search", help="Search local knowledge")
    srch.add_argument("--db", default=DEFAULT_DB)
    srch.add_argument("--query", required=True)
    srch.add_argument("--limit", type=int, default=5)

    stats = sub.add_parser("stats", help="Show database statistics")
    stats.add_argument("--db", default=DEFAULT_DB)

    return parser


def main(argv=None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(message)s",
    )

    args = build_parser().parse_args(argv)

    try:
        if args.command == "init":
            conn = connect(args.db)
            conn.close()

            result = {
                "status": "ready",
                "database": str(Path(args.db).resolve()),
            }

        elif args.command == "seed":
            topics = list(DEFAULT_SEED_TOPICS)
            if args.topics_file:
                topics.extend(read_topics_file(args.topics_file))
            result = seed_topics(
                db_path=args.db,
                topics=topics,
                delay=args.delay,
                timeout=args.timeout,
                limit=args.limit,
            )

        elif args.command == "fetch-topic":
            result = fetch_and_store_topic(
                db_path=args.db,
                topic=args.topic,
                timeout=args.timeout,
            )
            result["database"] = str(Path(args.db).expanduser().resolve())

        elif args.command == "wikipedia":
            if not Path(args.dump).is_file():
                raise FileNotFoundError(
                    f"Dump file not found: {args.dump}"
                )

            result = import_records(
                args.db,
                wikipedia_pages(args.dump, args.language),
                args.limit,
                args.batch_size,
            )

        elif args.command == "wikidata":
            if not Path(args.dump).is_file():
                raise FileNotFoundError(
                    f"Dump file not found: {args.dump}"
                )

            result = import_records(
                args.db,
                wikidata_entities(args.dump),
                args.limit,
                args.batch_size,
            )

        elif args.command == "import-both":
            wiki_path = Path(args.wikipedia_dump)
            wikidata_path = Path(args.wikidata_dump)
            if not wiki_path.is_file():
                raise FileNotFoundError(f"Wikipedia dump file not found: {wiki_path}")
            if not wikidata_path.is_file():
                raise FileNotFoundError(f"Wikidata dump file not found: {wikidata_path}")

            # Both sources are written to the same documents table/database.
            wiki_result = import_records(
                args.db,
                wikipedia_pages(str(wiki_path), args.language),
                args.wikipedia_limit,
                args.batch_size,
            )
            wikidata_result = import_records(
                args.db,
                wikidata_entities(str(wikidata_path)),
                args.wikidata_limit,
                args.batch_size,
            )
            result = {
                "status": "imported_both_sources",
                "database": str(Path(args.db).resolve()),
                "wikipedia": wiki_result,
                "wikidata": wikidata_result,
            }

        elif args.command == "search":
            result = search(args.db, args.query, args.limit)

        elif args.command == "stats":
            conn = connect(args.db)

            try:
                total = conn.execute(
                    "SELECT COUNT(*) FROM documents"
                ).fetchone()[0]

                counts = {
                    row[0]: row[1]
                    for row in conn.execute(
                        """
                        SELECT source, COUNT(*)
                        FROM documents
                        GROUP BY source
                        """
                    )
                }

            finally:
                conn.close()

            result = {
                "total_documents": total,
                "by_source": counts,
            }

        else:
            return 2

        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    except (OSError, ValueError, sqlite3.Error) as exc:
        LOG.error("Knowledge operation failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
