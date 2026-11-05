"""Offline importers for ARIA's seven free knowledge collections.

No API keys or language models are used. Download datasets separately and import
them from local files. All records are stored in the same SQLite database used by
brain.knowledge.open_knowledge, so ARIA's existing local retrieval can search them.

Supported collections:
  wikipedia, wikidata, stackexchange, openstax, pubmed, gutenberg, openalex

Examples:
  python -m brain.knowledge.dataset_importer catalog
  python -m brain.knowledge.dataset_importer import --source stackexchange --file Posts.xml
  python -m brain.knowledge.dataset_importer import --source openstax --file textbook.epub
  python -m brain.knowledge.dataset_importer import --source pubmed --file baseline.xml.gz
  python -m brain.knowledge.dataset_importer import --source gutenberg --file book.txt
  python -m brain.knowledge.dataset_importer import --source openalex --file works.jsonl.gz
"""
from __future__ import annotations

import argparse
import bz2
import gzip
import hashlib
import html
import json
import logging
import re
import sqlite3
import sys
from datetime import datetime, timezone
import zipfile
from itertools import islice
from pathlib import Path
from typing import Iterable, Iterator
from urllib.parse import quote, urljoin
from html.parser import HTMLParser
import xml.etree.ElementTree as ET

from brain.knowledge.open_knowledge import DEFAULT_DB, import_records

LOG = logging.getLogger("aria.dataset_importer")
MAX_CONTENT_CHARS = 250_000

DATASETS = {
    "wikipedia": {
        "description": "General encyclopedia: science, history, geography, people, technology.",
        "url": "https://dumps.wikimedia.org/",
        "format": "MediaWiki XML dump (.xml or .xml.bz2); use open_knowledge wikipedia command",
        "license": "CC BY-SA and GFDL; retain attribution and comply with dump terms",
    },
    "wikidata": {
        "description": "Structured facts, entities, dates, places, and relationships.",
        "url": "https://www.wikidata.org/wiki/Wikidata:Database_download",
        "format": "Wikidata JSON dump (often .json.bz2); use open_knowledge wikidata command",
        "license": "Structured data is generally CC0; verify the specific dump",
    },
    "stackexchange": {
        "description": "Programming Q&A and troubleshooting from selected Stack Exchange sites.",
        "url": "https://archive.org/details/stackexchange",
        "format": "Posts.xml from a Stack Exchange data dump",
        "license": "Usually CC BY-SA; preserve post links, authors/attribution where supplied, and license",
    },
    "openstax": {
        "description": "Textbook-level biology, physics, chemistry, math, and astronomy.",
        "url": "https://openstax.org/subjects",
        "format": "Downloaded .txt, .html, .htm, .epub, or .pdf textbook",
        "license": "Check each book; many are CC BY-NC-SA (non-commercial restriction)",
    },
    "pubmed": {
        "description": "Biomedical citations and abstracts for research discovery.",
        "url": "https://pubmed.ncbi.nlm.nih.gov/download/",
        "format": "PubMed XML baseline/update file (.xml, .xml.gz, or .xml.gz in an archive)",
        "license": "Metadata/abstract rights vary; follow NLM and publisher terms",
    },
    "gutenberg": {
        "description": "Public-domain literature and historical texts.",
        "url": "https://www.gutenberg.org/ebooks/",
        "format": "UTF-8 .txt, .txt.gz, or .epub file",
        "license": "Verify public-domain status in your jurisdiction and preserve notices",
    },
    "openalex": {
        "description": "Scholarly work metadata, authors, institutions, and abstracts when available.",
        "url": "https://help.openalex.org/access/snapshot/",
        "format": "OpenAlex works JSONL (.jsonl, .jsonl.gz, or JSON-lines .gz)",
        "license": "Review current OpenAlex terms; full snapshot is very large",
    },
    "codingdocs": {
        "description": "Offline programming-language and developer documentation in HTML, Markdown, text, PDF, or EPUB form.",
        "url": "https://docs.python.org/3/download.html",
        "format": "A single supported document or a directory tree of docs; pass --base-url to preserve canonical source links",
        "license": "Varies by documentation project; preserve per-source license and attribution before importing or redistributing",
    },
}


def _open_text(path: Path):
    suffixes = "".join(path.suffixes).lower()
    if suffixes.endswith(".bz2"):
        return bz2.open(path, "rt", encoding="utf-8", errors="replace")
    if suffixes.endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return path.open("rt", encoding="utf-8", errors="replace")


def _clean(value) -> str:
    value = html.unescape(str(value or ""))
    value = re.sub(r"<script\b[^>]*>.*?</script>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<style\b[^>]*>.*?</style>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:MAX_CONTENT_CHARS]


def _record(source: str, source_id: str, title: str, content: str,
            url: str = "", language: str = "en") -> dict:
    return {
        "source": source, "source_id": str(source_id)[:300],
        "title": _clean(title)[:500], "content": _clean(content),
        "url": str(url or "")[:2000], "language": language,
        "license": {
            "stackexchange": "CC BY-SA; preserve attribution",
            "openstax": "Check individual textbook license",
            "pubmed": "Metadata/abstract rights vary; verify record terms",
            "gutenberg": "Verify public-domain status and notices",
            "openalex": "Verify current OpenAlex snapshot terms",
            "codingdocs": "Preserve each documentation project's license and attribution; verify before redistribution",
        }.get(source, "unknown"),
    }


def _stackexchange(path: Path) -> Iterator[dict]:
    # Data dump Posts.xml uses one <row .../> per post. iterparse keeps memory bounded.
    with _open_text(path) as stream:
        for _, elem in ET.iterparse(stream, events=("end",)):
            if elem.tag != "row":
                elem.clear()
                continue
            a = elem.attrib
            post_id = a.get("Id")
            body = _clean(a.get("Body", ""))
            title = _clean(a.get("Title", ""))
            post_type = a.get("PostTypeId", "")
            if post_id and body and (post_type in {"1", "2"} or title):
                # Answers use ParentId; questions retain title.
                parent = a.get("ParentId")
                label = title or (f"Answer to Stack Exchange post {parent}" if parent else f"Stack Exchange post {post_id}")
                url = f"https://stackoverflow.com/questions/{parent or post_id}" if parent else f"https://stackoverflow.com/q/{post_id}"
                yield _record("stackexchange", post_id, label, body, url)
            elem.clear()


def _pubmed(path: Path) -> Iterator[dict]:
    # Parse one PubMedArticle at a time to support large baseline XML files.
    with _open_text(path) as stream:
        for _, elem in ET.iterparse(stream, events=("end",)):
            tag = elem.tag.rsplit("}", 1)[-1]
            if tag != "PubmedArticle":
                continue
            try:
                pmid = elem.findtext(".//PMID") or ""
                title = " ".join((elem.findtext(".//ArticleTitle") or "").split())
                abstract_parts = []
                for node in elem.findall(".//Abstract/AbstractText"):
                    txt = " ".join("".join(node.itertext()).split())
                    if txt:
                        label = node.attrib.get("Label")
                        abstract_parts.append(f"{label}: {txt}" if label else txt)
                abstract = " ".join(abstract_parts)
                if pmid and title and abstract:
                    yield _record("pubmed", pmid, title, abstract,
                                  f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/")
            finally:
                elem.clear()


def _openalex(path: Path) -> Iterator[dict]:
    with _open_text(path) as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                LOG.warning("Skipping invalid JSON on line %d", line_number)
                continue
            work_id = str(item.get("id") or item.get("ids", {}).get("openalex") or "")
            title = item.get("title") or item.get("display_name") or ""
            abstract = item.get("abstract") or ""
            # OpenAlex commonly stores inverted-index abstracts rather than plain text.
            if isinstance(abstract, dict):
                positions = []
                for word, indexes in abstract.items():
                    for index in indexes or []:
                        positions.append((int(index), word))
                abstract = " ".join(word for _, word in sorted(positions))
            if not abstract and isinstance(item.get("abstract_inverted_index"), dict):
                positions = []
                for word, indexes in item["abstract_inverted_index"].items():
                    for index in indexes or []:
                        positions.append((int(index), word))
                abstract = " ".join(word for _, word in sorted(positions))
            if not work_id or not title:
                continue
            # Avoid polluting retrieval with title-only records where no abstract exists.
            content = _clean(abstract) or _clean(title)
            if content:
                yield _record("openalex", work_id, title, content, work_id)


def _epub(path: Path) -> Iterator[dict]:
    # EPUB is a ZIP of XHTML. Yield one chapter per file.
    try:
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if not name.lower().endswith((".xhtml", ".html", ".htm")):
                    continue
                try:
                    raw = archive.read(name).decode("utf-8", errors="replace")
                except (KeyError, RuntimeError):
                    continue
                content = _clean(raw)
                if len(content) >= 150:
                    title = Path(name).stem.replace("_", " ").replace("-", " ")
                    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:16]
                    yield _record("openstax", f"{path.stem}:{digest}", title, content,
                                  f"file://{path.resolve()}#{quote(name)}")
    except zipfile.BadZipFile as exc:
        raise ValueError(f"Invalid EPUB/ZIP file: {path}") from exc


def _text_or_html(path: Path, source: str) -> Iterator[dict]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError("PDF import requires pypdf; install requirements.txt") from exc
        reader = PdfReader(str(path))
        buffer = []
        for index, page in enumerate(reader.pages, 1):
            text = _clean(page.extract_text() or "")
            if text:
                buffer.append((index, text))
        # Chunk at page groups for searchability and bounded record sizes.
        for start in range(0, len(buffer), 5):
            pages = buffer[start:start + 5]
            content = "\n".join(f"[Page {n}] {txt}" for n, txt in pages)
            if content.strip():
                yield _record(source, f"{path.stem}:pages:{pages[0][0]}-{pages[-1][0]}",
                              f"{path.stem} (pages {pages[0][0]}-{pages[-1][0]})",
                              content, DATASETS.get(source, {}).get("url", ""))
        return
    if suffix == ".epub":
        for rec in _epub(path):
            rec["source"] = source
            rec["url"] = DATASETS.get(source, {}).get("url", rec.get("url", ""))
            yield rec
        return
    with _open_text(path) as stream:
        index = 0
        chunk = []
        chars = 0
        for line in stream:
            line = _clean(line)
            if not line:
                continue
            chunk.append(line)
            chars += len(line)
            if chars >= 12_000:
                index += 1
                yield _record(source, f"{path.stem}:{index}", f"{path.stem} (section {index})",
                              " ".join(chunk), DATASETS.get(source, {}).get("url", ""))
                chunk, chars = [], 0
        if chunk:
            index += 1
            yield _record(source, f"{path.stem}:{index}", f"{path.stem} (section {index})",
                          " ".join(chunk), DATASETS.get(source, {}).get("url", ""))


class _HTMLTextExtractor(HTMLParser):
    """Small standard-library HTML text extractor that retains document title."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_title = False
        self.title_parts = []
        self.text_parts = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "title":
            self.in_title = True
        if tag in {"script", "style", "noscript", "svg"}:
            self.skip_depth += 1
        if tag in {"p", "div", "section", "article", "li", "h1", "h2", "h3", "pre", "br"}:
            self.text_parts.append("\n")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "title":
            self.in_title = False
        if tag in {"script", "style", "noscript", "svg"} and self.skip_depth:
            self.skip_depth -= 1
        if tag in {"p", "div", "section", "article", "li", "h1", "h2", "h3", "pre", "br"}:
            self.text_parts.append("\n")

    def handle_data(self, data):
        if self.in_title:
            self.title_parts.append(data)
        if not self.skip_depth:
            self.text_parts.append(data)


def _codingdocs(path: Path, base_url: str = "") -> Iterator[dict]:
    """Import individual documentation pages with stable IDs and canonical URLs."""
    supported = {".html", ".htm", ".md", ".markdown", ".txt", ".rst", ".pdf", ".epub"}
    ignored_parts = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
    files = [path] if path.is_file() else sorted(
        item for item in path.rglob("*")
        if item.is_file() and item.suffix.lower() in supported
        and not any(part in ignored_parts for part in item.parts)
    )
    root = path.parent if path.is_file() else path
    base = base_url.strip()
    if base and not base.endswith("/"):
        base += "/"
    for file_path in files:
        suffix = file_path.suffix.lower()
        rel = file_path.name if path.is_file() else file_path.relative_to(root).as_posix()
        if rel.startswith("files/en-us/"):
            # MDN's source repository stores pages under files/en-us/<slug>.md;
            # map these to the corresponding published /en-US/docs/<slug> URL.
            rel = rel[len("files/en-us/"):]
            rel = re.sub(r"\.(?:md|markdown)$", "", rel, flags=re.I)
            rel = re.sub(r"(?:^|/)index$", "", rel, flags=re.I).strip("/")
        elif suffix in {".md", ".markdown"}:
            rel = re.sub(r"\.(?:md|markdown)$", "", rel, flags=re.I)
        if suffix == ".pdf":
            try:
                from pypdf import PdfReader
            except ImportError as exc:
                raise RuntimeError("PDF import requires pypdf; install requirements.txt") from exc
            reader = PdfReader(str(file_path))
            url = urljoin(base, quote(rel)) if base else ""
            page_text = []
            for page_number, page in enumerate(reader.pages, 1):
                page_content = _clean(page.extract_text() or "")
                if page_content:
                    page_text.append((page_number, page_content))
            digest = hashlib.sha1(rel.encode("utf-8")).hexdigest()[:20]
            for index in range(0, len(page_text), 5):
                group = page_text[index:index + 5]
                content = "\n".join(f"[Page {number}] {text}" for number, text in group)
                if content:
                    yield _record("codingdocs", f"{digest}:pages:{group[0][0]}-{group[-1][0]}",
                                  f"{file_path.stem} (pages {group[0][0]}-{group[-1][0]})", content, url)
            continue
        if suffix == ".epub":
            for rec in _epub(file_path):
                rec["source"] = "codingdocs"
                rec["url"] = urljoin(base, quote(rel)) if base else ""
                yield rec
            continue
        try:
            raw = _open_text(file_path).read()
        except (OSError, UnicodeError) as exc:
            LOG.warning("Skipping unreadable documentation file %s: %s", file_path, exc)
            continue
        title = ""
        if suffix in {".html", ".htm"}:
            parser = _HTMLTextExtractor()
            try:
                parser.feed(raw)
                title = _clean(" ".join(parser.title_parts))
                raw = " ".join(parser.text_parts)
            except Exception:
                raw = _clean(raw)
        else:
            raw = re.sub(r"(?s)^---\s*\n.*?\n---\s*\n", "", raw, count=1)
            raw = re.sub(r"!?(\[[^\]]*\])\([^)]*\)", r"\1", raw)
            title_match = re.search(r"(?m)^#\s+(.+)$", raw)
            title = _clean(title_match.group(1)) if title_match else ""
        content = _clean(raw)
        if len(content) < 40:
            continue
        title = title or file_path.stem.replace("_", " ").replace("-", " ")
        url = urljoin(base, quote(rel)) if base else ""
        digest = hashlib.sha1(rel.encode("utf-8")).hexdigest()[:20]
        # Split long documents into bounded overlapping-ish chunks, preserving page title/URL.
        for index, start in enumerate(range(0, len(content), 10_000), 1):
            chunk = content[start:start + 10_000]
            if len(chunk) < 40:
                continue
            chunk_title = title if index == 1 else f"{title} (part {index})"
            yield _record("codingdocs", f"{digest}:{index}", chunk_title, chunk, url)


def records_for(source: str, path: Path, base_url: str = "") -> Iterable[dict]:
    source = source.lower()
    if source == "codingdocs":
        return _codingdocs(path, base_url=base_url)
    if source == "stackexchange":
        return _stackexchange(path)
    if source == "pubmed":
        return _pubmed(path)
    if source == "openalex":
        return _openalex(path)
    if source in {"openstax", "gutenberg"}:
        return _text_or_html(path, source)
    raise ValueError(
        f"Source '{source}' is imported with open_knowledge.py's wikipedia/wikidata commands."
    )


def _file_fingerprint(path: Path) -> dict:
    """Return a lightweight, deterministic input identity without reading huge dumps twice."""
    if path.is_file():
        stat = path.stat()
        return {"kind": "file", "path": str(path.resolve()), "size_bytes": stat.st_size, "modified_ns": stat.st_mtime_ns}
    files = []
    for child in sorted(item for item in path.rglob("*") if item.is_file()):
        try:
            stat = child.stat()
        except OSError:
            continue
        files.append({"relative_path": child.relative_to(path).as_posix(), "size_bytes": stat.st_size, "modified_ns": stat.st_mtime_ns})
    encoded = json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {"kind": "directory", "path": str(path.resolve()), "file_count": len(files), "metadata_sha256": hashlib.sha256(encoded).hexdigest()}


def _find_unchanged_import(db_path: str, source: str, path: Path) -> dict | None:
    """Return the latest matching completed import, if the input fingerprint is unchanged."""
    fingerprint = _file_fingerprint(path)
    if not Path(db_path).exists():
        return None
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        table = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='dataset_import_runs'").fetchone()
        if not table:
            return None
        row = conn.execute(
            "SELECT fingerprint_json, result_json FROM dataset_import_runs "
            "WHERE source=? AND input_path=? ORDER BY id DESC LIMIT 1",
            (source, str(path.resolve())),
        ).fetchone()
        if not row or row[0] != json.dumps(fingerprint, ensure_ascii=False, sort_keys=True):
            return None
        try:
            previous = json.loads(row[1])
        except (TypeError, json.JSONDecodeError):
            return None
        if previous.get("status") == "failed" or previous.get("dry_run") is True:
            return None
        return previous
    finally:
        conn.close()


def _record_import_run(db_path: str, source: str, path: Path, result: dict, limit) -> None:
    """Record successful imports; this never skips or alters document records."""
    fingerprint = _file_fingerprint(path)
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS dataset_import_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, input_path TEXT NOT NULL,
            fingerprint_json TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT NOT NULL,
            requested_limit INTEGER, processed_records INTEGER NOT NULL DEFAULT 0,
            database_changes INTEGER NOT NULL DEFAULT 0, result_json TEXT NOT NULL
        )""")
        finished = datetime.now(timezone.utc).isoformat()
        processed = int(result.get("processed", result.get("processed_records", 0)) or 0)
        changed = int(result.get("changed", result.get("database_changes", 0)) or 0)
        conn.execute("""INSERT INTO dataset_import_runs
            (source, input_path, fingerprint_json, started_at, finished_at, requested_limit, processed_records, database_changes, result_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (source, str(path.resolve()), json.dumps(fingerprint, ensure_ascii=False, sort_keys=True),
             finished, finished, limit, processed, changed, json.dumps(result, ensure_ascii=False, default=str, sort_keys=True)))
        conn.commit()
    finally:
        conn.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Import free knowledge datasets into ARIA's local SQLite corpus")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("catalog", help="List supported datasets and download pages")
    imp = sub.add_parser("import", help="Import a downloaded local dataset file")
    imp.add_argument("--source", required=True, choices=sorted(DATASETS))
    imp.add_argument("--file", required=True)
    imp.add_argument("--db", default=DEFAULT_DB)
    imp.add_argument("--limit", type=int, default=None)
    imp.add_argument("--batch-size", type=int, default=250)
    imp.add_argument("--dry-run", action="store_true", help="Preview records without writing to the database")
    imp.add_argument("--skip-unchanged", action="store_true", help="Skip import if the same source and input fingerprint were imported previously")
    imp.add_argument("--preview-count", type=int, default=10, help="Maximum records inspected during --dry-run (1-100)")
    imp.add_argument("--base-url", default="", help="Canonical base URL for codingdocs imports, e.g. https://docs.python.org/3/")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        if args.command == "catalog":
            print(json.dumps(DATASETS, ensure_ascii=False, indent=2))
            return 0
        path = Path(args.file).expanduser()
        if not path.exists() or (not path.is_file() and not (args.source == "codingdocs" and path.is_dir())):
            raise FileNotFoundError(f"Dataset file/directory not found: {path}")
        if args.source in {"wikipedia", "wikidata"}:
            raise ValueError(
                f"Use `python -m brain.knowledge.open_knowledge {args.source} --dump \"{path}\" --db \"{args.db}\"`."
            )
        if args.batch_size < 1:
            raise ValueError("--batch-size must be at least 1")
        if args.limit is not None and args.limit < 0:
            raise ValueError("--limit must be zero or greater")

        if args.skip_unchanged and not args.dry_run:
            previous = _find_unchanged_import(args.db, args.source, path)
            if previous is not None:
                result = {
                    "dry_run": False,
                    "skipped": True,
                    "reason": "unchanged_input_fingerprint",
                    "source": args.source,
                    "input_file": str(path.resolve()),
                    "previous_processed_records": int(previous.get("processed", previous.get("processed_records", 0)) or 0),
                    "database_written": False,
                    "manifest_recorded": False,
                    "note": "Input file metadata matches the most recent recorded import. Use without --skip-unchanged to force a re-import.",
                }
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 0

        records = records_for(args.source, path, base_url=args.base_url)
        if args.dry_run:
            if not 1 <= args.preview_count <= 100:
                raise ValueError("--preview-count must be between 1 and 100")
            preview_limit = min(args.preview_count, args.limit) if args.limit is not None else args.preview_count
            preview = list(islice(records, preview_limit))
            result = {
                "dry_run": True,
                "source": args.source,
                "input_file": str(path.resolve()),
                "records_previewed": len(preview),
                "preview_limit": preview_limit,
                "database_written": False,
                "records": [
                    {
                        "source": str(item.get("source", "")),
                        "source_id": str(item.get("source_id", "")),
                        "title": str(item.get("title", ""))[:200],
                        "content_characters": len(str(item.get("content", ""))),
                        "url": str(item.get("url", "")),
                        "license": str(item.get("license", "unknown")),
                    }
                    for item in preview
                ],
                "note": "Preview only; this does not validate or import the entire dataset.",
            }
        else:
            result = import_records(args.db, records, args.limit, args.batch_size)
            result.update({"dry_run": False})
            _record_import_run(args.db, args.source, path, result, args.limit)
            result["manifest_recorded"] = True
        result.update({"source": args.source, "input_file": str(path.resolve())})
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, sqlite3.Error, RuntimeError, ET.ParseError) as exc:
        LOG.error("Import failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
