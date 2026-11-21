"""Exact-reference protections and reproducible retrieval-evaluation tests."""
from __future__ import annotations

import json

import pytest

from document_agent import hybrid
from document_agent.retrieval_ids import matches_reference, requested_references
from document_agent.tools import search_documents
from scripts.evaluate_retrieval import demo_cases, demo_database, evaluate, read_cases


class IndifferentEncoder:
    def encode(self, texts, **kwargs):
        return [[1.0, 0.0, 0.0] for _ in texts]


def test_references_are_whole_and_do_not_match_longer_ids():
    assert requested_references("Compare EL-103, EL-1030 and CO-07") == [
        "el-103", "el-1030", "co-07"
    ]
    assert requested_references("follow-up, 2026-11-21") == []
    assert matches_reference("EL-103", ["el-103"])
    assert not matches_reference("EL-1030", ["el-103"])
    assert matches_reference("EL-1030", ["el-1030"])


@pytest.mark.parametrize(
    ("query", "expected_row"),
    [("What is EL-103 worth?", 2), ("Price of EL-1030?", 3),
     ("What is the amount for EL-101?", 4)],
)
def test_exact_reference_keyword_query_never_returns_neighbor(query, expected_row):
    conn = demo_database()
    response = search_documents(conn, query, mode="keyword")
    assert [hit["citation"] for hit in response["results"]] == [
        f"BOQ.xlsx | Items | row {expected_row}"
    ]
    conn.close()


def test_multiple_requested_ids_return_both_records():
    conn = demo_database()
    response = search_documents(conn, "Compare EL-103 and EL-1030", mode="keyword")
    assert {hit["citation"] for hit in response["results"]} == {
        "BOQ.xlsx | Items | row 2", "BOQ.xlsx | Items | row 3"
    }
    conn.close()


def test_hybrid_filters_wrong_reference_even_with_high_vector_similarity(monkeypatch):
    conn = demo_database()
    monkeypatch.setattr(hybrid, "embedding_model", IndifferentEncoder)
    result = search_documents(conn, "Show price for EL-103", mode="hybrid")
    assert result["retrieval_mode"] == "hybrid"
    assert [hit["citation"] for hit in result["results"]] == [
        "BOQ.xlsx | Items | row 2"
    ]
    conn.close()


def test_benchmark_keyword_metrics_are_reproducible():
    conn = demo_database()
    report = evaluate(conn, demo_cases(), mode="keyword", k=10)
    assert report["valid_for_mode"]
    assert report["cases"] == len(demo_cases())
    assert report["hit_rate_at_k"] > 0
    assert all(len(detail["retrieved_citations"]) <= 10 for detail in report["details"])
    conn.close()


def test_benchmark_does_not_mislabel_keyword_fallback_as_hybrid(monkeypatch):
    conn = demo_database()

    def missing_model():
        raise hybrid.EmbeddingUnavailable("not cached")

    monkeypatch.setattr(hybrid, "embedding_model", missing_model)
    report = evaluate(
        conn, [{"query": "EL-103",
                "expected_citations": ["BOQ.xlsx | Items | row 2"]}],
        mode="hybrid", k=3,
    )
    assert not report["valid_for_mode"]
    assert report["fallback_cases"] == 1
    assert report["details"][0]["actual_mode"] == "keyword"
    conn.close()


def test_bad_gold_cases_cannot_be_silently_used(tmp_path):
    p = tmp_path / "cases.json"
    p.write_text(json.dumps([{"query": "What is the cost?"}]), encoding="utf-8")
    with pytest.raises(ValueError, match="expected_citations"):
        read_cases(p)
