"""Validated, provenance-aware importer for curated ARIA specialized knowledge packs.

The default command is preview-only. Import requires --execute and an existing SQLite
knowledge database. Files are plain Markdown or text; the manifest carries attribution.
"""
from __future__ import annotations
import argparse, hashlib, json, re, sqlite3, sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

DEFAULT_MANIFEST = Path(__file__).with_name("specialized_docs_manifest.json")
ALLOWED_EXTENSIONS = {".md", ".markdown", ".txt"}
MAX_FILE_BYTES = 1_000_000
MAX_DOCUMENTS = 100


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def load_manifest(manifest_path: str | Path, docs_root: str | Path | None = None) -> dict[str, Any]:
    manifest_path = Path(manifest_path).expanduser().resolve()
    root = Path(docs_root).expanduser().resolve() if docs_root else manifest_path.parent
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("documents"), list):
        raise ValueError("Manifest must be an object with a 'documents' list")
    docs = raw["documents"]
    if len(docs) > MAX_DOCUMENTS:
        raise ValueError(f"Manifest exceeds the {MAX_DOCUMENTS}-document safety limit")
    seen: set[str] = set(); validated = []
    for index, item in enumerate(docs):
        if not isinstance(item, dict): raise ValueError(f"documents[{index}] must be an object")
        required = ("id", "title", "domain", "path", "source_url", "license", "language")
        missing = [key for key in required if not _nonempty(item.get(key))]
        if missing: raise ValueError(f"documents[{index}] missing: {', '.join(missing)}")
        doc_id = item["id"].strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,119}", doc_id):
            raise ValueError(f"Invalid document id: {doc_id!r}")
        if doc_id in seen: raise ValueError(f"Duplicate document id: {doc_id}")
        seen.add(doc_id)
        rel = Path(item["path"])
        if rel.is_absolute() or ".." in rel.parts: raise ValueError(f"Unsafe document path: {rel}")
        full = (root / rel).resolve()
        if not full.is_relative_to(root): raise ValueError(f"Document path escapes docs root: {rel}")
        if full.suffix.lower() not in ALLOWED_EXTENSIONS: raise ValueError(f"Unsupported file type: {full.suffix}")
        parsed = urlparse(item["source_url"].strip())
        if parsed.scheme != "https" or not parsed.netloc: raise ValueError(f"source_url must be an HTTPS URL: {doc_id}")
        if not full.is_file(): raise FileNotFoundError(f"Document file not found: {full}")
        if full.stat().st_size > MAX_FILE_BYTES: raise ValueError(f"Document exceeds {MAX_FILE_BYTES} bytes: {doc_id}")
        content = full.read_text(encoding="utf-8").strip()
        if len(content) < 40: raise ValueError(f"Document content is too short (<40 chars): {doc_id}")
        validated.append({**item, "id": doc_id, "title": item["title"].strip(), "domain": item["domain"].strip(),
                          "path": str(full), "content": content,
                          "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest()})
    return {"manifest": str(manifest_path), "docs_root": str(root), "documents": validated,
            "document_count": len(validated)}


def import_specialized_docs(db_path: str | Path, manifest_path: str | Path = DEFAULT_MANIFEST,
                            docs_root: str | Path | None = None, execute: bool = False) -> dict[str, Any]:
    db = Path(db_path).expanduser().resolve()
    if not db.is_file(): raise FileNotFoundError(f"Knowledge database does not exist: {db}; no database was created")
    pack = load_manifest(manifest_path, docs_root)
    report: dict[str, Any] = {"status": "preview", "execute_requested": execute,
        "database": str(db), "document_count": pack["document_count"],
        "documents": [{"id": d["id"], "title": d["title"], "domain": d["domain"],
                       "source_url": d["source_url"], "license": d["license"], "sha256": d["sha256"]}
                      for d in pack["documents"]], "inserted": 0, "skipped_existing": 0}
    if not execute: return report
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=rw", uri=True, timeout=15)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(documents)")}
        needed = {"source", "source_id", "title", "content", "url", "language", "license"}
        if not needed.issubset(cols):
            raise RuntimeError("Target database does not have the expected ARIA 'documents' schema")
        inserted = skipped = 0
        with conn:
            for d in pack["documents"]:
                cur = conn.execute("""INSERT OR IGNORE INTO documents
                    (source, source_id, title, content, url, language, license)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    ("specialized_docs:" + d["domain"], d["id"], d["title"], d["content"],
                     d["source_url"], d["language"], d["license"]))
                if cur.rowcount == 1: inserted += 1
                else: skipped += 1
        report.update(status="imported", inserted=inserted, skipped_existing=skipped)
        return report
    finally: conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Preview or import curated specialized knowledge documents")
    parser.add_argument("--db", required=True, help="Path to an existing ARIA SQLite knowledge database")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--docs-root", default=None)
    parser.add_argument("--execute", action="store_true", help="Actually import; default is preview-only")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(import_specialized_docs(args.db, args.manifest, args.docs_root, args.execute), indent=2, ensure_ascii=False))
        return 0
    except (OSError, ValueError, sqlite3.Error, RuntimeError, json.JSONDecodeError) as exc:
        print(f"ARIA specialized-doc import failed: {exc}", file=sys.stderr); return 2

if __name__ == "__main__": raise SystemExit(main())
