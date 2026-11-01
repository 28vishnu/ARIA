# JARVIS knowledge database

## SQLite corpus schema

The existing `documents` table and `(source, source_id)` identity are preserved.
`open_knowledge.connect()` applies an additive schema-version 2 migration and records
version 2 in `knowledge_schema_migrations`. It adds canonical URL/summary, domain and
subject IDs, topic IDs, publication/retrieval/verification dates, content SHA-256,
document version, quality/freshness scores, verification status and JSON metadata.
It creates `document_history` for prior content revisions and indexes for taxonomy,
publication date and content-hash lookups. Existing rows are not discarded or
rewritten during connection. Existing records receive taxonomy assignments only when
their title exactly matches a catalogue topic during a later import/update.

FTS5 is an external-content index with change triggers where supported. SQLite builds
without FTS5 use the existing bounded LIKE fallback. The Mongo knowledge collection,
Chroma vectors, structured-fact tables and graph remain separate existing subsystems;
this release does not duplicate them into SQLite.

## Migration and recovery

The migration is additive and idempotent. Back up persistent data before deploying.
The supplied archive contained no live corpus, so no user database was migrated during
this work. The first write-capable `connect()` in a deployed updated service applies
the migration. Inspect the migration table and run read-only verification after the
first connection.

```text
python -m brain.knowledge.open_knowledge verify --db data/aria_open_knowledge.sqlite3
python -m brain.knowledge.open_knowledge backup --db data/aria_open_knowledge.sqlite3 --destination data/backups/knowledge.sqlite3
python -m brain.knowledge.open_knowledge restore --source data/backups/knowledge.sqlite3 --destination data/restored.sqlite3
python -m brain.knowledge.open_knowledge reindex --db data/aria_open_knowledge.sqlite3
```

Backup refuses to overwrite an existing file. Restore targets a new path by default;
`--overwrite` is an explicit replacement option and should only be used after a
separate verified backup. Keep SQLite files on persistent storage and include MongoDB
and Chroma data in the deployment's backup plan.
