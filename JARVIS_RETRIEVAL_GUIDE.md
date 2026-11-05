# JARVIS retrieval guide

The user-facing route is the existing `KnowledgeManager.retrieve()` and
`KnowledgeManager.answer()` flow. It merges evidence from local SQLite, configured
knowledge/Mongo and Chroma stores, graph/world-model data, and active documents. The
answer composer receives ranked evidence from this shared path; Telegram and Android
use the same backend response route.

The local corpus uses FTS5 when available and LIKE otherwise. Vector retrieval is
available only if an embedder and compatible persisted collection initialize; a
lexical result must not be described as semantic retrieval. The five-bucket legacy
coverage report remains for compatibility, while the new exact-title taxonomy report
provides per-topic/domain lower-bound measurements.

For research-oriented questions, online fallback now queries arXiv and OpenAlex in
parallel with a maximum of 10 items per provider. It records publication dates,
authors, source URLs, record type and retrieval time, labels arXiv results as preprints,
and does not download full text. A provider failure is reported in provider status and
does not create a fake result. Results join the same evidence list and are not
automatically persisted as reusable corpus documents.

Current affairs and version-sensitive technical questions still require dated current
source evidence. Search snippets alone do not prove a claim. Health and legal
responses should remain educational and grounded in authoritative sources; this
retrieval layer is not an individualized professional advice service.
