# JARVIS knowledge architecture

## Data flow

The FastAPI lifespan bootstraps the knowledge manager, graph, vector store and
search tools. `KnowledgeManager.retrieve()` merges local Mongo/knowledge data,
SQLite FTS/LIKE results, structured and graph evidence, world-model evidence, and
explicitly active documents. It ranks this unified set, then the existing answer path
uses the evidence composer. When evidence is insufficient, `_online_fallback()` uses
the configured public search provider and, for research/paper queries, the bounded
arXiv and OpenAlex adapters in `brain/knowledge/academic_sources.py`. Wikimedia is
the small, on-demand knowledge fallback; RSS is collected by the existing idle
maintenance path. Academic full text is never downloaded by these adapters.

## Knowledge components

- **Catalogue:** `knowledge_taxonomy.json`, schema 1, taxonomy 1.0.0. It contains
  20 stable top-level IDs, subject and subdomain nodes, 378 topic records, source
  references, quality requirements, relationships, learning objectives, questions,
  prerequisites, concepts/entities slots, and formula metadata where defined.
- **Candidate acquisition list:** the existing `core_topics.txt` remains intact
  (787 entries). It is an acquisition list, not proof of corpus coverage.
- **Registry:** `source_registry.json` schema 2 describes both rights review and
  operational source metadata. `not_checked` means no provider health probe occurred.
- **Relational/lexical store:** SQLite documents table, FTS5 external-content index
  when available, and a LIKE fallback.
- **Semantic/graph/facts:** existing Chroma/embedding and Mongo knowledge paths,
  plus provenance-aware SQLite structured facts and the knowledge graph. Semantic
  search must be considered active only where bootstrap successfully configures its
  compatible embedder and index.
- **Evidence:** source URLs, license, publication/retrieval/verification dates,
  quality/freshness scores, content hashes, verification status and source metadata.
- **Maintenance:** incremental topic and RSS ingestion, resumable dump imports,
  daily refresh/audit tools, freshness schedules, readiness checks, and evaluation.

The catalogue and coverage are separate. An empty or missing database is reported as
such; domain or topic presence in JSON never counts as acquired knowledge.

## Retrieval and safeguards

Local evidence is attempted first. The query planner normalizes user framing; local
lexical search and configured vector retrieval share the knowledge manager. Online
fallback is bounded and source-backed. Current/research questions can use dated
provider records. arXiv results are labelled preprints. OpenAlex metadata does not
assert that a work is peer-reviewed or that third-party abstract/full text can be
redistributed. Provider failures return no fabricated results and do not stop the
other provider.

See `JARVIS_RETRIEVAL_GUIDE.md`, `JARVIS_KNOWLEDGE_SOURCES.md`, and
`JARVIS_KNOWLEDGE_DATABASE.md` for operational details.
