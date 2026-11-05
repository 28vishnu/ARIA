# JARVIS knowledge implementation status

Date: 2026-11-01

## Implemented in this pass

- Audited the current topic, database, registry, retrieval, answer, freshness,
  structured-fact, graph, batch-ingestion, coverage, readiness and evaluation modules
  before extending them.
- Added `knowledge_taxonomy.json`: 20 stable top-level domains, hierarchical subject
  and subdomain nodes, 378 topic records, required metadata, registered source IDs,
  related-topic edges, source quality expectations, and curated formula metadata.
- Added taxonomy validation/listing/read-only exact-title coverage commands and made
  the existing `knowledge_domains` CLI expose taxonomy commands while keeping its
  legacy five domain keys and safe default sync.
- Extended the central source registry to schema 2 with operational and rights fields.
  All taxonomy source IDs resolve; source entries with no active adapter are labelled
  as registry-only or otherwise explicitly limited.
- Added bounded live arXiv and OpenAlex search adapters and wired academic-intent
  fallback into the existing unified knowledge answer route. Full-text downloads and
  automatic persistence of these search abstracts are not performed.
- Added additive SQLite document metadata migration, content hashes, taxonomy
  assignment on exact topic-title imports, version history for changed content,
  read-only integrity checks, guarded backup/restore and FTS reindex operations.
- Extended retrieval evaluation with fixed relevance labels and P@K, R@K, MRR,
  citation URL correctness, evidence previews and latency. Added a 27-case dataset.
- Added the eight requested knowledge architecture/source/database/ingestion/retrieval/
  evaluation/domain/status documents and focused tests for taxonomy, adapters,
  source registry, migration, versioning and backup/restore.

## Verification and blockers

| Check | Status |
| --- | --- |
| Taxonomy JSON structural audit via PowerShell | PASS — 20 domains, 378 topics, required fields present, all referenced source IDs registered |
| Original topic seed file | PRESERVED — 787 candidate entries; catalogue membership does not imply acquisition |
| Python unit tests | NOT RUN — bundled Python 3.12 lacks `pytest`; syntax compilation, taxonomy validation/rendering, source audit, readiness, and SQLite import/search/version/backup/restore smoke checks pass |
| arXiv/OpenAlex live calls | NOT VERIFIED — network/provider behavior requires test runner and external access |
| Existing database migration | NOT RUN — supplied archive had no database; migration is additive and idempotent in code |
| Corpus coverage / evaluation report | NOT VERIFIED — no populated corpus was supplied |
| Vector semantic retrieval | Environment-dependent — only active when a compatible embedder/index initializes |

## Remaining limitations

- The taxonomy is a curated, expandable retrieval catalogue, not complete human
  knowledge and not proof every listed topic is covered by the corpus.
- Direct adapters for Wikidata SPARQL, MDN, NIST, government portals, WHO and UNESCO
  remain registry-only; existing RSS configuration is the current feed path.
- There is no universal queued ingestion manager with pause/cancel/retry-failed-record
  controls across all dataset formats.
- Answer-level completeness and unsupported-claim evaluation need reviewed gold
  answers and a populated corpus; current metrics evaluate retrieval only.
- Production backups, data migration, provider credentials, Android/backend behavior,
  and deployment were not exercised.
