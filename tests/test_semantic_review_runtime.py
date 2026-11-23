"""Runtime semantic review is optional, evidence-bound and non-destructive."""
from __future__ import annotations

from document_agent.agent import Answer
from document_agent.db import connect
from document_agent.semantic_review_runtime import review_answer


def _setup(source: str, claim: str):
    conn = connect(":memory:")
    conn.execute(
        "INSERT INTO documents(path,kind,status) VALUES('Report.pdf','pdf','ready')"
    )
    conn.execute(
        "INSERT INTO passages(document_id,page,chunk,text) VALUES(1,1,0,?)",
        (source,),
    )
    citation = "Report.pdf | page 1 | chunk 0"
    answer = Answer(
        text=claim + " — " + citation,
        sources=[citation],
        tool_calls=[{"name": "search_documents", "ok": True}],
        verification_status="evidence_linked",
        claims=[{"text": claim, "status": "evidence_linked",
                 "sources": [citation]}],
    )
    return conn, answer, citation


def test_correct_paraphrase_upgrades_when_original_quote_valid():
    source = "Two independent samples failed laboratory quality-control checks."
    conn, answer, citation = _setup(
        source, "Lab quality checks failed for 2 independent samples."
    )
    try:
        result = review_answer(
            conn, "How many independent samples failed?", answer,
            lambda q, a, e: {
                "supported": True, "complete": True,
                "supporting_quotes": [{"citation": citation, "quote": source}],
            },
        )
        assert result.verification_status == "semantic_supported"
        assert result.tool_calls[-1]["name"] == "semantic_verification"
        assert result.tool_calls[-1]["ok"]
    finally:
        conn.close()


def test_wrong_quantity_cannot_pass_even_when_judge_says_supported():
    source = "The warehouse dispatch confirmed four pallets."
    conn, answer, citation = _setup(
        source, "The warehouse confirmed 5 pallets."
    )
    try:
        result = review_answer(
            conn, "How many pallets were confirmed?", answer,
            lambda q, a, e: {
                "supported": True, "complete": True,
                "supporting_quotes": [{"citation": citation, "quote": source}],
            },
        )
        assert result.verification_status == "evidence_linked"
        assert result.tool_calls[-1]["ok"] is False
    finally:
        conn.close()


def test_judge_outage_does_not_reject_answer():
    conn, answer, citation = _setup(
        "The panel approved the laboratory testing procedure.",
        "The panel authorized laboratory testing.",
    )
    try:
        def failing_judge(question, text, evidence):
            raise RuntimeError("temporary quota")

        result = review_answer(conn, "What was approved?", answer, failing_judge)
        assert result.verification_status == "evidence_linked"
        assert result.sources == [citation]
        assert result.tool_calls[-1]["ok"] is False
    finally:
        conn.close()


def test_unverified_claims_not_promoted_to_semantic_support():
    conn, answer, _ = _setup(
        "The committee's request is pending signature.",
        "The committee approved the request.",
    )
    try:
        answer.claims[0]["status"] = "unverified"
        called = []

        def judge(q, a, e):
            called.append(True)
            return {}

        result = review_answer(conn, "Was this signed?", answer, judge)
        assert result.verification_status == "evidence_linked"
        assert not called
    finally:
        conn.close()


def test_incomplete_retrieval_not_upgraded_by_model():
    conn, answer, _ = _setup(
        "A milestone is scheduled for 20 July 2028.",
        "The milestone is 20 July 2028.",
    )
    try:
        answer.tool_calls.append({"name": "search_documents", "incomplete": True})
        result = review_answer(conn, "What are all milestone dates?", answer,
                               lambda q, a, e: {})
        assert result.verification_status == "evidence_linked"
        assert not any(x["name"] == "semantic_verification"
                       for x in result.tool_calls)
    finally:
        conn.close()
