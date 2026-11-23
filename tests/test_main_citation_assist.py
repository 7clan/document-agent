"""Citation improvements must never turn main into PR10's semantic verifier."""
from __future__ import annotations

import json

from document_agent.agent import _source_linked_answer
from document_agent.citation_assist import (
    _literal_support,
    citation_assist,
    indexed_records,
    recover_literal_source,
    related_source_locations,
)
from document_agent.db import connect


def corpus():
    conn = connect(":memory:")
    docs = [
        (1, "Contract.pdf", "pdf"),
        (2, "Variation.pdf", "pdf"),
        (3, "Pending.pdf", "pdf"),
        (4, "Costs.xlsx", "xlsx"),
        (5, "Minutes.docx", "docx"),
    ]
    conn.executemany(
        "INSERT INTO documents(id,path,kind,status) VALUES(?,?,?,'ready')",
        docs,
    )
    passages = [
        (1, 1, 0, "Drone surveys, emergency battery banks, and cloud hosting "
         "subscriptions are excluded. Original signed value SAR 8,750,000."),
        (2, 1, 0, "The signed variation approved SAR 315,000. "
         "Revised authorized contract value SAR 9,065,000."),
        (3, 1, 0, "CR-12 proposes new water meters. This request is unsigned "
         "and not approved. Proposed cost SAR 450,000."),
    ]
    conn.executemany(
        "INSERT INTO passages(document_id,page,chunk,text) VALUES(?,?,?,?)",
        passages,
    )
    conn.execute(
        "INSERT INTO sheet_rows(document_id,sheet,row_num,cells_json) VALUES(4,'Costs',2,?)",
        (json.dumps({"A": {"value": "AW-405"},
                     "B": {"value": "Commissioning services"},
                     "C": {"value": 980000}}),),
    )
    conn.execute(
        "INSERT INTO word_blocks(document_id,ordinal,kind,location,section,text) "
        "VALUES(5,1,'paragraph','paragraph 1','Schedule',"
        "'The internal readiness forecast is 12 October 2029.')",
    )
    conn.commit()
    return conn


def draft(statement, supports=None):
    return json.dumps({
        "answer": statement, "insufficient": False,
        "claims": [{"text": statement, "supports": supports or []}],
    })


def test_missing_model_citation_is_recovered_from_long_literal_original():
    conn = corpus()
    try:
        sentence = ("Drone surveys, emergency battery banks, and cloud "
                    "hosting subscriptions are excluded from the agreement.")
        answer = _source_linked_answer(
            conn, draft(sentence), [], [{"name": "search_documents", "ok": True}],
            "Name three excluded categories.",
        )
        assert sentence in answer.text
        assert answer.sources == ["Contract.pdf | page 1 | chunk 0"]
        assert answer.claims[0]["quotes"][0]["quote"].startswith("Drone surveys")
        assert answer.tool_calls[-1]["literal_citations_recovered"] == 1
        assert answer.verification_status == "evidence_linked"
        assert "fact-checked" in answer.tool_calls[-1]["reason"]
    finally:
        conn.close()


def test_different_scope_or_negation_never_gets_direct_citation():
    source = "The signed request has not been approved for wireless meters."
    claim = "The signed request has been approved for wireless meters."
    assert not _literal_support(claim, source)
    assert not _literal_support(
        "Authorized new smart meters for SAR 950,000 and delivery.",
        "Authorized new smart meters for SAR 450,000 and delivery.",
    )


def test_derived_calculation_stays_visible_without_literal_amount():
    conn = corpus()
    try:
        claim = ("Seven percent of the original signed contract value "
                 "results in SAR 612,500 in retention.")
        answer = _source_linked_answer(
            conn, draft(claim), [],
            [{"name": "search_documents", "ok": True}],
            "What is the original contract retention amount?",
        )
        assert claim in answer.text
        assert answer.verification_status == "unverified"
        assert not answer.sources
        assert answer.claims[0]["sources"] == []
        # This is a citation finder, not a rule that rejects valid math.
        assert "source reference unavailable" in answer.text
        assert answer.tool_calls[-1]["literal_citations_recovered"] == 0
    finally:
        conn.close()


def test_extra_distinct_document_locations_are_suggestions_not_verified_claims():
    conn = corpus()
    try:
        claim = "The revised authorized contract value is SAR 9,065,000."
        verified = "Variation.pdf | page 1 | chunk 0"
        answer = _source_linked_answer(
            conn, draft(claim, [{"citation": verified}]), [verified],
            [{"name": "search_documents", "ok": True}],
            "After signed variation, what is the binding contract value? "
            "Do not include pending CR-12 water meters.",
        )
        assert answer.sources == [verified]
        assert answer.claims[0]["sources"] == [verified]
        assert answer.verification_status == "evidence_linked"
        candidates = (answer.structured or {}).get("candidate_sources", [])
        assert "Pending.pdf | page 1 | chunk 0" in candidates
        assert verified not in candidates
        assert answer.tool_calls[-1]["name"] == "source_linking"
        assert answer.tool_calls[-1]["additional_source_locations"] >= 1
    finally:
        conn.close()


def test_disabled_mode_returns_original_source_behavior(monkeypatch):
    monkeypatch.setenv("DOCUMENT_AGENT_CITATION_ASSIST", "0")
    conn = corpus()
    try:
        claim = "Drone surveys, emergency battery banks, and cloud hosting subscriptions are excluded."
        answer = _source_linked_answer(
            conn, draft(claim), [], [{"name": "search_documents", "ok": True}],
            "Name three excluded categories.",
        )
        assert answer.sources == []
        assert answer.verification_status == "unverified"
        assert (answer.structured or {}).get("candidate_sources", []) == []
        assert answer.tool_calls[-1]["literal_citations_recovered"] == 0
    finally:
        conn.close()


def test_fabricated_model_reference_is_not_silently_replaced():
    conn = corpus()
    try:
        claim = "Drone surveys, emergency battery banks, and cloud hosting subscriptions are excluded."
        answer = _source_linked_answer(
            conn, draft(claim, [{"citation": "Unknown.pdf | page 9 | chunk 9"}]),
            ["Contract.pdf | page 1 | chunk 0"],
            [{"name": "search_documents", "ok": True}],
            "Name three excluded categories.",
        )
        assert not answer.sources
        assert answer.claims[0]["status"] == "unverified"
        assert answer.tool_calls[-1]["literal_citations_recovered"] == 0
    finally:
        conn.close()


def test_citation_assist_uses_indexed_pdf_word_spreadsheet_locations_only():
    conn = corpus()
    try:
        all_records = indexed_records(conn)
        names = {x["citation"] for x in all_records}
        assert "Costs.xlsx | Costs | row 2" in names
        assert "Minutes.docx | paragraph 1" in names
        assert "Contract.pdf | page 1 | chunk 0" in names
        assert indexed_records(conn, limit=2) == all_records[:2]
        assert recover_literal_source(
            "Drone surveys, emergency battery banks, and cloud hosting subscriptions are excluded.",
            all_records,
        ) == ["Contract.pdf | page 1 | chunk 0"]
        _, ranked = citation_assist(
            "What is the signed variation value?",
            ["Revised authorized contract value SAR 9,065,000"],
            conn, [],
        )
        assert all(source in names for source in ranked)
        assert related_source_locations("the and the", [], all_records) == []
    finally:
        conn.close()
