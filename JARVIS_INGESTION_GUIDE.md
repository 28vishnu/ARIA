# JARVIS ingestion guide

Ingestion is an operator action, not part of API startup. Small live topic fetches are
bounded; bulk corpora must be downloaded separately, rights-reviewed and imported
incrementally. Do not place a Wikipedia-scale download into the service process.

## Safe workflow

1. Inspect `knowledge_domains sources` and verify license, attribution, and terms for
   the exact source artifact.
2. Check storage capacity and back up the existing SQLite corpus.
3. Use `dataset_importer import --dry-run` with a small preview before a full import.
4. Use the applicable source-specific importer with `--limit` and bounded batch size.
5. Review processed counts and errors; rerunning a source ID updates the same record,
   and changed content is versioned into `document_history`.
6. Run `open_knowledge verify`, `corpus_status`, `knowledge_readiness`, and the
   versioned coverage command. These checks do not claim factual correctness.

Examples:

```text
python -m brain.knowledge.dataset_importer catalog
python -m brain.knowledge.dataset_importer import --source codingdocs --file data/python-docs --base-url https://docs.python.org/3/ --dry-run
python -m brain.knowledge.dataset_importer import --source openstax --file data/textbook.epub --limit 2000 --batch-size 100
python -m brain.knowledge.open_knowledge fetch-topic --topic "Binary search" --db data/aria_open_knowledge.sqlite3
python -m brain.knowledge.knowledge_domains sync --domain computer_science --limit-per-domain 5
```

Current resumability is provided by stable source IDs, transactional batches and the
dataset importer run manifest. The project does not yet expose a unified queued job
API with pause/cancel/retry-failed-record controls for every adapter. Do not claim
those controls are available.
