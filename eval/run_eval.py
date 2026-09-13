"""Retrieval + answer evaluation harness against a golden query set.

Usage:
    python3 eval/run_eval.py

Exits with code 1 if more than 30% of queries fail to clear the confidence bar —
use this as a CI regression gate after embedder swaps, LLM changes, or prompt edits.
"""
import json
import sys
import os

# Ensure project root is on the import path when running as a script
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Trigger registration of parsers/embedders
import ingestion.parsers  # noqa: F401
import retrieval.embedder  # noqa: F401
import retrieval.vector_store  # noqa: F401

from retrieval.retriever import hybrid_retrieve, graph_augment
from llm.orchestrator import answer
from retrieval.router import classify_query, RouteType


def load_golden_set(path: str = None):
    if path is None:
        path = os.path.join(os.path.dirname(__file__), "golden_set.json")
    with open(path) as f:
        return json.load(f)


def evaluate_retrieval(golden_set):
    """Measures Recall@8: fraction of golden cases where expected docs appear in top-8 results."""
    hits, total = 0, 0
    for case in golden_set:
        expected = set(case.get("expected_doc_ids", []))
        if not expected:
            continue  # skip cases without expected_doc_ids populated yet
        chunks = hybrid_retrieve(case["query"], top_k=8)
        retrieved_doc_ids = {c.doc_id for c in chunks}
        total += 1
        if expected & retrieved_doc_ids:
            hits += 1
    recall_at_8 = hits / total if total else None
    return {"recall_at_8": recall_at_8, "cases_with_doc_ids": total, "hits": hits}


def evaluate_routing(golden_set):
    """Logs the query router classification for each case — use this to spot misclassifications."""
    results = []
    for case in golden_set:
        route = classify_query(case["query"])
        results.append({"query": case["query"], "route": route.value})
    return results


def evaluate_end_to_end(golden_set):
    """Runs answer() for each case and reports confidence + citation count."""
    results = []
    for case in golden_set:
        try:
            result = answer(case["query"])
            results.append({
                "query": case["query"],
                "confidence": result["confidence"],
                "citations_count": len(result["citations"]),
                "answered": result["confidence"] >= 0.5,
                "answer_snippet": result["answer"][:120] + "..." if len(result["answer"]) > 120 else result["answer"],
            })
        except Exception as e:
            results.append({
                "query": case["query"],
                "confidence": 0.0,
                "citations_count": 0,
                "answered": False,
                "error": str(e),
            })
    return results


if __name__ == "__main__":
    import ingestion.parsers  # trigger registrations

    golden_set = load_golden_set()

    print("=" * 60)
    print(" RETRIEVAL METRICS")
    print("=" * 60)
    retrieval_metrics = evaluate_retrieval(golden_set)
    print(json.dumps(retrieval_metrics, indent=2))

    print("\n" + "=" * 60)
    print(" QUERY ROUTING")
    print("=" * 60)
    routing_results = evaluate_routing(golden_set)
    for r in routing_results:
        print(f"  [{r['route'].upper():12s}] {r['query']}")

    print("\n" + "=" * 60)
    print(" END-TO-END RESULTS")
    print("=" * 60)
    e2e_results = evaluate_end_to_end(golden_set)
    for r in e2e_results:
        status = "PASS" if r["answered"] else "FAIL"
        err = f" ERROR: {r.get('error', '')}" if "error" in r else ""
        print(f"  [{status}] conf={r['confidence']:.2f} citations={r['citations_count']} — {r['query']}{err}")
        if r.get("answer_snippet"):
            print(f"         → {r['answer_snippet']}")

    fail_count = sum(1 for r in e2e_results if not r["answered"])
    total = len(e2e_results)
    fail_rate = fail_count / total if total else 0.0
    print(f"\n  {fail_count}/{total} queries below confidence threshold ({fail_rate:.0%} fail rate)")

    # Fail CI if more than 30% of queries don't clear the confidence bar
    sys.exit(1 if fail_rate > 0.3 else 0)
