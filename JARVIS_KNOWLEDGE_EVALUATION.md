# JARVIS knowledge evaluation

`brain/knowledge/knowledge_evaluation_cases.json` is dataset
`jarvis-knowledge-retrieval-core` version 1.0.0. It has 27 fixed query cases spanning
all 20 top-level domains, additional programming/AI/biology queries, and multilingual,
current-weather and current-release cases.
Reference titles/URLs are retrieval targets, not gold answer text. No LLM output is
used as ground truth. Current weather and release cases explicitly require live data
and cannot pass based on stale local content.

Run against a populated corpus:

```text
python -m brain.knowledge.retrieval_evaluation --db data/aria_open_knowledge.sqlite3 --cases brain/knowledge/knowledge_evaluation_cases.json --top-k 5 --report-out outputs/knowledge-evaluation.json
```

Reports include query, expected domain/route, returned document IDs, source URLs,
scores, evidence previews, latency and pass/fail. Precision@K, recall@K, MRR and
citation URL correctness are calculated only for cases with fixed relevance labels.
Answer completeness and unsupported-claim rate are explicitly `null`: this tool
evaluates retrieval, not generated answer truth. Coverage and retrieval scores must
not be represented as factual accuracy. A corpus-backed report was not produced here
because the archive contains no populated database and Python was unavailable in the
execution environment.
