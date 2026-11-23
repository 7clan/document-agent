"""Recovery is bounded, provenance preserving, and provider independent."""
from __future__ import annotations

import json

from document_agent.agent import (
    Answer,
    _explicit_money,
    _infer_exact_item_file,
    _needs_numeric_query,
    _source_linked_answer,
    _verified_numeric_answer,
)
from document_agent.db import connect
from document_agent.evidence_ledger import build_ledger
from document_agent.query_plan import plan_question
from document_agent.recovery import recover_answer


def _db():
    conn = connect(":memory:")
    conn.execute("INSERT INTO documents(id,path,kind,status) "
                 "VALUES(1,'Contract.pdf','pdf','ready'),"
                 "(2,'BOQ.xlsx','xlsx','ready')")
    conn.execute("INSERT INTO passages(document_id,page,chunk,text) VALUES"
                 "(1,1,0,'Change order CO-12 is approved. The revised sum is SAR 7,070,000.')")
    cells = {"A": {"value": "EL-103"}, "B": {"value": "Switchgear panel"},
             "C": {"value": 890000}}
    conn.execute("INSERT INTO sheet_rows(document_id,sheet,row_num,cells_json) "
                 "VALUES(2,'Base',4,?)", (json.dumps(cells),))
    return conn


def _draft(text: str, citation: str = "") -> str:
    return json.dumps({"answer": text, "insufficient": False,
                       "claims": [{"text": text, "supports": (
                           [{"citation": citation}] if citation else [])}]})


def test_plan_is_validated_and_mixed_scope_keeps_other_documents_eligible():
    conn = _db()
    plan = plan_question(conn, "What is CO-12 in Contract.pdf and EL-103 in BOQ.xlsx?")
    assert plan.scope_kind == "mixed"
    assert set(plan.document_scope) == {"Contract.pdf", "BOQ.xlsx"}
    assert "search_documents" in plan.required_operations
    assert set(plan.identifiers) == {"co-12", "el-103"}


def test_ledger_resolves_original_passages_and_rejects_inventory_as_fact():
    conn = _db()
    ledger = build_ledger(conn, ["Contract.pdf | page 1 | chunk 0",
                                 "BOQ.xlsx | Base | row 4",
                                 "Contract.pdf | document",
                                 "Fake.pdf | page 1 | chunk 0"])
    assert set(ledger) == {"Contract.pdf | page 1 | chunk 0",
                           "BOQ.xlsx | Base | row 4"}
    assert ledger["BOQ.xlsx | Base | row 4"].cells["A"] == "EL-103"
    assert ledger["Contract.pdf | page 1 | chunk 0"].status_terms == ("approved",)


def test_first_attempt_retrieves_missing_exact_identifier_and_second_can_correct():
    conn = _db()
    question = "What does Contract.pdf say about CO-12?"
    plan = plan_question(conn, question)
    initial = Answer("No grounded answer", [], [], verification_status="unverified")
    calls = []

    def regenerate(citations):
        calls.append(citations)
        citation = "Contract.pdf | page 1 | chunk 0"
        return _source_linked_answer(conn, _draft("CO-12 is approved.", citation),
                                     citations, [{"name": "recovery", "ok": True}])

    result = recover_answer(conn, question, plan, initial, regenerate)
    assert calls == [["Contract.pdf | page 1 | chunk 0"]]
    assert result.sources == ["Contract.pdf | page 1 | chunk 0"]
    assert result.verification_status == "evidence_linked"
    assert [call["attempt"] for call in result.tool_calls if "attempt" in call] == [1, 2]


def test_unresolved_recovery_stops_after_two_attempts_without_inventing_source():
    conn = _db()
    question = "What is the telephone number for EL-999?"
    plan = plan_question(conn, question)
    initial = Answer("Not found", [], [], verification_status="unverified")
    called = []
    result = recover_answer(conn, question, plan, initial,
                            lambda citations: called.append(citations))
    assert not called
    assert result.sources == []
    assert result.verification_status == "unverified"
    assert len([call for call in result.tool_calls
                if call.get("name") == "recovery_retrieval"]) <= 2


def test_recovery_provider_failure_is_safe_and_does_not_retry_again():
    conn = _db()
    citation = "Contract.pdf | page 1 | chunk 0"
    initial = _source_linked_answer(
        conn, _draft("CO-12 is approved.", "Fake.pdf | page 1 | chunk 0"),
        [citation], [{"name": "search_documents", "ok": True},
                     {"name": "evidence_handoff", "citations": [citation]}])

    def fail(_):
        raise RuntimeError("secret provider response")

    result = recover_answer(conn, "Is CO-12 approved?", plan_question(
        conn, "Is CO-12 approved?"), initial, fail)
    assert result.verification_status == "unverified"
    event = next(call for call in result.tool_calls
                 if call.get("name") == "recovery_regeneration")
    assert event["attempt"] == 2 and event["error_type"] == "RuntimeError"
    assert "secret" not in str(result.tool_calls)


def test_fabricated_amount_and_identifier_remain_unverified():
    conn = _db()
    citation = "Contract.pdf | page 1 | chunk 0"
    for claim in ("CO-13 is approved.", "The revised sum is SAR 8,070,000."):
        result = _source_linked_answer(
            conn, _draft(claim, citation), [citation],
            [{"name": "get_evidence", "ok": True}])
        assert result.verification_status == "unverified"
        assert result.claims[0]["status"] == "unverified"


def test_absence_claim_with_existing_citation_is_not_verified():
    conn = _db()
    citation = "Contract.pdf | page 1 | chunk 0"
    claim = "The revised contract sum is not found in the indexed documents."
    result = _source_linked_answer(conn, _draft(claim, citation), [citation],
                                   [{"name": "search_documents", "ok": True}])
    assert result.verification_status == "unverified"
    assert "Absence cannot be established" in result.claims[0]["reason"]


def test_false_absence_is_not_headlined_when_original_evidence_was_retrieved():
    conn = _db()
    citation = "Contract.pdf | page 1 | chunk 0"
    payload = json.dumps({"answer": "The revised sum is not found.",
                          "insufficient": True, "claims": []})
    result = _source_linked_answer(conn, payload, [citation],
                                   [{"name": "search_documents", "ok": True}])
    assert result.text.startswith("The model could not establish a complete answer")
    assert "The revised sum is not found" not in result.text
    assert result.structured["candidate_sources"] == [citation]


def test_rejected_correction_is_still_recorded_in_audit():
    conn = _db()
    citation = "Contract.pdf | page 1 | chunk 0"
    initial = _source_linked_answer(
        conn, _draft("CO-12 is approved.", "Fake.pdf | page 1 | chunk 0"),
        [citation], [{"name": "evidence_handoff", "citations": [citation]}])
    unchanged = Answer("Still no answer", [], [], verification_status="unverified")
    result = recover_answer(conn, "Is CO-12 approved?", plan_question(
        conn, "Is CO-12 approved?"), initial, lambda _: unchanged)
    assert result is initial
    assert any(event.get("name") == "recovery_regeneration" and
               event.get("accepted") is False for event in result.tool_calls)


def test_question_threshold_is_not_mistaken_for_fabricated_source_amount():
    assert _explicit_money("SAR 1 million") == _explicit_money("SAR 1,000,000")
    assert _needs_numeric_query("Does EL-103 exceed SAR 1 million?")
    assert _needs_numeric_query("Total all signed-base amounts strictly above SAR 1 million")
    assert not _needs_numeric_query("What amount did the parties originally sign for?")


def test_named_sheet_numeric_scope_ignores_unrelated_corrupt_pdf():
    conn = connect(":memory:")
    conn.execute("INSERT INTO documents(id,path,kind,status,error) VALUES"
                 "(1,'Prices.xlsx','xlsx','ready',''),"
                 "(2,'Damaged.pdf','pdf','failed','bad PDF')")
    rows = {1: ["Item Ref", "Extended Amount (SAR)"],
            2: ["EL-103", 890000], 3: ["EL-104", 1200000]}
    for number, values in rows.items():
        cells = {chr(65 + index): {"value": value}
                 for index, value in enumerate(values)}
        conn.execute("INSERT INTO sheet_rows(document_id,sheet,row_num,cells_json) "
                     "VALUES(1,'Signed Base',?,?)", (number, json.dumps(cells)))
    single = _verified_numeric_answer(conn, "Does EL-103 exceed SAR 1 million?", {}, [])
    assert single.verification_status == "deterministically_verified"
    assert single.text.startswith("No. Item EL-103 is SAR 890000")
    aggregate = _verified_numeric_answer(
        conn, "List every Signed-Base cost item strictly above SAR 1 million.", {}, [])
    assert aggregate.verification_status == "deterministically_verified"
    assert aggregate.structured["verified_args"]["file"] == "Prices.xlsx"
    assert aggregate.structured["matched_amount_sum"] == "1200000"
    assert not aggregate.structured["warnings"]


def test_unique_exact_phrase_can_relink_an_omitted_citation_without_model_call():
    conn = _db()
    citation = "Contract.pdf | page 1 | chunk 0"
    statement = "Change order CO-12 is approved."
    initial = _source_linked_answer(
        conn, _draft(statement), [citation],
        [{"name": "search_documents", "ok": True},
         {"name": "evidence_handoff", "citations": [citation]}])
    called = []
    result = recover_answer(conn, statement, plan_question(conn, statement),
                            initial, lambda _: called.append(True))
    assert result.verification_status == "evidence_linked"
    assert result.sources == [citation]
    assert not called
    assert any(event.get("name") == "recovery_exact_link" for event in result.tool_calls)


def test_bad_explicit_citation_is_never_silently_relinked():
    conn = _db()
    citation = "Contract.pdf | page 1 | chunk 0"
    statement = "Change order CO-12 is approved."
    initial = _source_linked_answer(
        conn, _draft(statement, "Fake.pdf | page 1 | chunk 0"), [citation],
        [{"name": "evidence_handoff", "citations": [citation]}])
    result = recover_answer(conn, statement, plan_question(conn, statement), initial)
    assert result.verification_status == "unverified"
    assert result.sources == []
    assert not any(event.get("name") == "recovery_exact_link"
                   for event in result.tool_calls)


def test_unsupported_amount_gets_one_targeted_correction_and_revalidation():
    conn = _db()
    citation = "Contract.pdf | page 1 | chunk 0"
    wrong = _source_linked_answer(
        conn, _draft("The revised sum is SAR 8,070,000.", citation), [citation],
        [{"name": "search_documents", "ok": True}])
    assert wrong.verification_status == "unverified"
    calls = []

    def regenerate(citations):
        calls.append(citations)
        return _source_linked_answer(
            conn, _draft("The revised sum is SAR 7,070,000.", citation), citations,
            [{"name": "recovery_compact_final", "ok": True}])

    result = recover_answer(conn, "What is the revised sum?",
                            plan_question(conn, "What is the revised sum?"),
                            wrong, regenerate)
    assert len(calls) == 1
    assert result.verification_status == "evidence_linked"
    assert "7,070,000" in result.text


def test_shared_budget_counts_provider_corrections_before_postflight():
    conn = _db()
    question = "What does CO-12 say?"
    one = Answer("No grounded answer", [], [{"name": "evidence_retry"}],
                 verification_status="unverified")
    calls = []
    result = recover_answer(conn, question, plan_question(conn, question), one,
                            lambda _: calls.append(True))
    assert not calls
    assert [event["attempt"] for event in result.tool_calls
            if event.get("name") == "recovery_retrieval"] == [2]
    two = Answer("No grounded answer", [], [{"name": "evidence_retry"},
                                            {"name": "format_retry"}],
                 verification_status="unverified")
    blocked = recover_answer(conn, question, plan_question(conn, question), two,
                             lambda _: calls.append(True))
    assert not calls
    assert not any(event.get("name") == "recovery_retrieval"
                   for event in blocked.tool_calls)
    assert "budget exhausted" in blocked.text


def test_exact_item_file_is_not_inferred_if_code_exists_in_two_workbooks():
    conn = _db()
    conn.execute("INSERT INTO documents(id,path,kind,status) "
                 "VALUES(3,'Other.xlsx','xlsx','ready')")
    cells = {"A": {"value": "EL-103"}, "B": {"value": None}}
    conn.execute("INSERT INTO sheet_rows(document_id,sheet,row_num,cells_json) "
                 "VALUES(3,'Other',2,?)", (json.dumps(cells),))
    assert _infer_exact_item_file(conn, "EL-103", {}) == {}
