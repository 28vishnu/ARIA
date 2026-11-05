"""Read-only retrieval evaluation and knowledge-gap reporting for ARIA.

This module is a transparent lexical baseline, not an LLM judge or a claim of
semantic correctness. It reads an existing ARIA SQLite documents table in
read-only mode and never modifies source documents or the database.
"""
from __future__ import annotations
import argparse
import json
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Iterable

TOKEN_RE = re.compile(r"[a-z0-9]+", re.I)


def tokens(text: str) -> set[str]:
    return {t.casefold() for t in TOKEN_RE.findall(str(text or "")) if len(t) > 1}


def load_documents(db_path: str | Path) -> list[dict[str, Any]]:
    path = Path(db_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Knowledge database does not exist: {path}; no database was created")
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "documents" not in tables:
            raise ValueError("Database has no 'documents' table")
        columns = {r[1] for r in conn.execute("PRAGMA table_info(documents)")}
        required = {"id", "source", "title", "content", "url"}
        if not required.issubset(columns):
            raise ValueError("Documents table is missing required ARIA columns: " + ", ".join(sorted(required - columns)))
        return [dict(r) for r in conn.execute("SELECT id, source, title, content, url FROM documents ORDER BY id")]
    finally:
        conn.close()


def score_document(query_tokens: set[str], document: dict[str, Any]) -> float:
    title_tokens = tokens(document.get("title", ""))
    content_tokens = tokens(document.get("content", ""))
    if not query_tokens:
        return 0.0
    # Title matches are weighted higher; normalize against query size.
    title_hits = len(query_tokens & title_tokens)
    content_hits = len(query_tokens & content_tokens)
    return round((2 * title_hits + content_hits) / (3 * len(query_tokens)), 6)


def retrieve(query: str, documents: Iterable[dict[str, Any]], top_k: int = 5) -> list[dict[str, Any]]:
    if top_k < 1 or top_k > 100:
        raise ValueError("top_k must be between 1 and 100")
    query_tokens = tokens(query)
    ranked = []
    for doc in documents:
        score = score_document(query_tokens, doc)
        if score > 0:
            ranked.append({"id": doc["id"], "source": doc["source"], "title": doc["title"],
                           "url": doc["url"], "score": score,
                           "evidence_preview": str(doc.get("content") or "")[:500]})
    ranked.sort(key=lambda item: (-item["score"], str(item["title"]).casefold(), int(item["id"])))
    return ranked[:top_k]


def evaluate_cases(db_path: str | Path, cases: list[dict[str, Any]], top_k: int = 5,
                   minimum_score: float = 0.15) -> dict[str, Any]:
    """Evaluate queries; each case may include expected_terms and expected_source_ids."""
    if not 0 <= minimum_score <= 1:
        raise ValueError("minimum_score must be between 0 and 1")
    documents = load_documents(db_path)
    results = []
    passed = 0
    for index, case in enumerate(cases, start=1):
        started = time.perf_counter()
        query = str(case.get("query", "")).strip()
        if not query:
            raise ValueError(f"Case {index} has an empty query")
        ranked = retrieve(query, documents, top_k)
        expected_terms = tokens(" ".join(map(str, case.get("expected_terms", []))))
        expected_ids = {str(value) for value in case.get("expected_source_ids", [])}
        expected_titles = {re.sub(r"[^\w ]", "", str(value).casefold()).strip()
                           for value in case.get("relevant_titles", [])}
        expected_titles.discard("")
        top_results = [r for r in ranked if r["score"] >= minimum_score]
        found_terms = tokens(" ".join(r["title"] for r in top_results))
        term_coverage = (len(expected_terms & found_terms) / len(expected_terms)) if expected_terms else None
        expected_id_hit = any(str(r["id"]) in expected_ids for r in top_results) if expected_ids else None
        judged = bool(expected_ids or expected_titles)
        relevant = [r for r in ranked if (str(r["id"]) in expected_ids if expected_ids else
                    re.sub(r"[^\w ]", "", str(r["title"]).casefold()).strip() in expected_titles)] if judged else []
        precision_at_k = (len(relevant) / top_k) if judged else None
        recall_at_k = (min(len(relevant), len(expected_ids or expected_titles)) / len(expected_ids or expected_titles)) if judged else None
        reciprocal_rank = (1 / (ranked.index(relevant[0]) + 1)) if relevant else (0.0 if judged else None)
        valid_citations = sum(bool(re.match(r"^https://[^\s]+$", str(r.get("url") or ""))) for r in relevant)
        citation_correctness = (valid_citations / len(relevant)) if relevant else (0.0 if judged else None)
        has_result = bool(top_results)
        case_pass = has_result and (term_coverage is None or term_coverage > 0) and (expected_id_hit is not False) and (bool(relevant) if judged else True)
        passed += int(case_pass)
        results.append({"case_id": case.get("id", index), "query": query, "pass": case_pass,
                        "result_count": len(top_results), "expected_term_coverage": round(term_coverage, 3) if term_coverage is not None else None,
                        "expected_source_id_hit": expected_id_hit,
                        "expected_domain": case.get("domain"), "retrieval_route": case.get("retrieval_route"),
                        "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                        "final_answer": None,
                        "answer_evaluation": "not_performed_by_retrieval_evaluator",
                        "precision_at_k": round(precision_at_k, 4) if precision_at_k is not None else None,
                        "recall_at_k": round(recall_at_k, 4) if recall_at_k is not None else None,
                        "reciprocal_rank": round(reciprocal_rank, 4) if reciprocal_rank is not None else None,
                        "citation_correctness": round(citation_correctness, 4) if citation_correctness is not None else None,
                        "results": ranked})
    count = len(results)
    judged_cases = [item for item in results if item["precision_at_k"] is not None]
    def average(field: str):
        values = [item[field] for item in judged_cases if item[field] is not None]
        return round(sum(values) / len(values), 4) if values else None
    return {"status": "ok", "read_only": True, "evaluation_method": "transparent lexical token overlap; title matches weighted 2x; relevance metrics use fixed relevant_titles or relevant source IDs; not semantic verification",
            "database": str(Path(db_path).expanduser().resolve()), "document_count": len(documents),
            "case_count": count, "passed_cases": passed, "failed_cases": count - passed,
            "pass_rate_percent": round(passed / count * 100, 2) if count else None,
            "minimum_score": minimum_score, "top_k": top_k,
            "metrics": {"judged_cases": len(judged_cases), "precision_at_k": average("precision_at_k"),
                        "recall_at_k": average("recall_at_k"), "mean_reciprocal_rank": average("reciprocal_rank"),
                        "citation_correctness": average("citation_correctness"),
                        "answer_completeness": None, "unsupported_claim_rate": None,
                        "note": "Answer completeness and unsupported claims require a separate reviewed answer-level evaluator."},
            "cases": results}


def build_gap_report(evaluation: dict[str, Any]) -> dict[str, Any]:
    gaps = []
    for case in evaluation.get("cases", []):
        if not case.get("pass"):
            gaps.append({"case_id": case.get("case_id"), "query": case.get("query"),
                         "gap_type": "no_relevant_lexical_result" if not case.get("result_count") else "expected_evidence_not_retrieved",
                         "recommended_action": "Review catalog coverage, source documents, query wording, and retrieval strategy; verify manually."})
    return {"status": "gap_report", "total_cases": evaluation.get("case_count", 0),
            "identified_gaps": len(gaps), "gaps": gaps,
            "limitation": "A lexical miss is not proof that knowledge is absent; semantic matches may be missed."}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate JARVIS lexical retrieval and report knowledge gaps")
    parser.add_argument("--db", required=True, help="Path to an existing ARIA knowledge SQLite database")
    parser.add_argument("--cases", required=True, help="JSON file containing a list of query test cases")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--minimum-score", type=float, default=0.15)
    parser.add_argument("--gaps-out", help="Optional path to write gap report JSON")
    parser.add_argument("--report-out", help="Optional path for a machine-readable evaluation report")
    args = parser.parse_args(argv)
    try:
        cases_path = Path(args.cases).expanduser()
        case_data = json.loads(cases_path.read_text(encoding="utf-8"))
        cases = case_data.get("cases") if isinstance(case_data, dict) else case_data
        if not isinstance(cases, list):
            raise ValueError("Cases JSON must be a list or an object containing a cases list")
        report = evaluate_cases(args.db, cases, args.top_k, args.minimum_score)
        if isinstance(case_data, dict):
            report["dataset_id"] = case_data.get("dataset_id")
            report["dataset_version"] = case_data.get("version")
        report["gap_report"] = build_gap_report(report)
        if args.gaps_out:
            out = Path(args.gaps_out).expanduser()
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report["gap_report"], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if args.report_out:
            out = Path(args.report_out).expanduser()
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    except (OSError, ValueError, sqlite3.Error, json.JSONDecodeError) as exc:
        print(f"ARIA retrieval evaluation failed: {exc}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
