# JARVIS hierarchical knowledge domains

The version-controlled data source is
[`brain/knowledge/knowledge_taxonomy.json`](brain/knowledge/knowledge_taxonomy.json).
It is separate from the retained `core_topics.txt` seed list. Topic IDs are stable
slugs scoped by domain and subject. The JSON hierarchy is domain → subject →
subdomain → topic. Topic records carry a canonical domain path, definitions/explanation
scope, concepts, entity/subtopic slots, relationships, common and advanced questions,
learning objectives, prerequisites, related concepts, recommended source IDs and
source quality requirements. `formula_metadata` is null for ordinary topics and
includes variables, units, assumptions, prerequisites and a worked example for the
initially curated formula topics.

The catalogue is a maintained set of retrieval targets, not a claim that each topic
has been ingested or evaluated. Current exact-title coverage is read from an existing
database and does not infer semantic/content coverage.

## Commands

From the repository root:

```text
python -m brain.knowledge.knowledge_domains list --kind domains
python -m brain.knowledge.knowledge_domains list --kind subjects --domain computer_science
python -m brain.knowledge.knowledge_domains list --kind topics --domain physics
python -m brain.knowledge.knowledge_domains coverage --db data/aria_open_knowledge.sqlite3
python -m brain.knowledge.knowledge_domains catalog
python -m brain.knowledge.knowledge_domains sources
```

Legacy five-bucket domain IDs remain accepted for compatibility. Taxonomy topic
acquisition is explicit, bounded by `--limit-per-domain`, and never runs as an
application-startup download:

```text
python -m brain.knowledge.knowledge_domains sync --domain computer_science --limit-per-domain 10
python -m brain.knowledge.knowledge_domains sync --domain physics --limit-per-domain 10
python -m brain.knowledge.knowledge_domains sync --domain all-taxonomy --limit-per-domain 2
```
