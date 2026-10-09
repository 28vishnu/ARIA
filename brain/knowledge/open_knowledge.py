
"""ARIA local open-knowledge importer.

Supports Wikipedia XML dumps and Wikidata JSON-lines dumps.
Uses SQLite, supports compressed .bz2/.gz inputs, resumable imports,
deduplication, source URLs, full-text search when FTS5 is available,
and a LIKE fallback otherwise.

Examples:
  python -m brain.knowledge.open_knowledge init --db data/aria_knowledge.sqlite3
  python -m brain.knowledge.open_knowledge wikipedia --dump data/wiki.xml.bz2 --db data/aria_knowledge.sqlite3 --limit 1000
  python -m brain.knowledge.open_knowledge wikidata --dump data/wikidata.json.bz2 --db data/aria_knowledge.sqlite3 --limit 1000
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
import xml.etree.ElementTree as ET

from pathlib import Path
from urllib.parse import quote

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
                        "content": clean_text(text),
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
            source, source_id, title, content, url, language
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(source, source_id) DO UPDATE SET
            title=excluded.title,
            content=excluded.content,
            url=excluded.url,
            language=excluded.language
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

            if not title or not source_id or not content:
                continue

            batch.append(
                (source, source_id, title, content, url, language)
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


def build_parser():
    parser = argparse.ArgumentParser(
        description="ARIA local open-knowledge importer"
    )

    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Initialize the database")
    init.add_argument("--db", default=DEFAULT_DB)

    wiki = sub.add_parser(
        "wikipedia", help="Import a Wikipedia XML dump"
    )
    wiki.add_argument("--dump", required=True)
    wiki.add_argument("--db", default=DEFAULT_DB)
    wiki.add_argument("--language", default="en")
    wiki.add_argument("--limit", type=int, default=None)
    wiki.add_argument("--batch-size", type=int, default=250)

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
