import sqlite3

from brain.knowledge.retrieval_evaluation import evaluate_cases


def test_fixed_relevance_labels_produce_retrieval_and_citation_metrics(tmp_path):
    db = tmp_path / "evaluation.sqlite3"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE documents (id INTEGER PRIMARY KEY, source TEXT, title TEXT, content TEXT, url TEXT)")
        conn.execute("INSERT INTO documents VALUES (1,'reference','Binary search','Binary search operates on sorted data.','https://example.org/binary-search')")
        conn.execute("INSERT INTO documents VALUES (2,'reference','Linear search','Linear search examines items in sequence.','https://example.org/linear-search')")

    report = evaluate_cases(str(db), [{
        "id": "binary-search", "query": "Explain binary search",
        "relevant_titles": ["Binary search"], "domain": "computer_science",
        "retrieval_route": "local_lexical",
    }], top_k=2, minimum_score=0.1)

    assert report["metrics"]["precision_at_k"] == 0.5
    assert report["metrics"]["recall_at_k"] == 1.0
    assert report["metrics"]["mean_reciprocal_rank"] == 1.0
    assert report["metrics"]["citation_correctness"] == 1.0
    assert report["cases"][0]["latency_ms"] >= 0
    assert report["cases"][0]["final_answer"] is None
