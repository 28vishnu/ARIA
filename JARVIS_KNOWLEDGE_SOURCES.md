# JARVIS knowledge sources

`brain/knowledge/source_registry.json` schema 2 is the central registry. It includes
provider/base URL, API or dataset type, taxonomy domains, license and attribution
review, terms URL, update frequency, rate-limit/auth notes, reliability class, last
successful sync, health state and ingestion method. Registry presence does not clear
rights or mean an adapter is active. All synchronization results should retain
canonical source URLs and record-level rights. Publisher or third-party content rights
remain distinct from metadata access.

## Active acquisition paths

| Source | Current path | Rights/quality handling |
| --- | --- | --- |
| Wikipedia/Wikidata | Existing bounded REST/entity API topic fetch and local dump importer | Article/dump license retained; title and source URL persisted |
| arXiv | New bounded Atom search adapter for research queries | Results labelled preprints; abstract metadata only, paper-specific rights apply |
| OpenAlex | New bounded Works API search adapter; optional `OPENALEX_API_KEY` | Bibliographic metadata; abstract rights may belong to third parties |
| Configured RSS/Atom | Existing bounded feed collector and state tracking | Dated item summaries and linked source URLs; excerpt rights remain publisher-specific |
| Tavily/web search | Existing configured search action | Search excerpts are labelled excerpts; original-page reuse rights are not assumed |
| Local archives | Existing Stack Exchange, OpenStax, PubMed, OpenAlex, Gutenberg and coding-document importers | Operator verifies each dataset/version/license before import |

## Registered but not directly integrated

Wikidata SPARQL, MDN, NIST, government portals, WHO and UNESCO are described in the
registry for source selection and future adapters. Entries state `registry_only` where
no runtime adapter exists. Do not infer support from a source's registry entry.

## Primary API references

- [arXiv API User's Manual](https://info.arxiv.org/help/api/user-manual.html)
- [OpenAlex API reference](https://help.openalex.org/api/)
- [OpenAlex Works API](https://help.openalex.org/data/works/)
- [Wikimedia REST API](https://www.mediawiki.org/wiki/Wikimedia_REST_API/en)

These URLs are recorded for operator review. Check provider terms, rate controls and
record-level rights before changing ingestion volume or retaining content.
