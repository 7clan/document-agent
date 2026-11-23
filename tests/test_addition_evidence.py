"""Fail-closed tests for original signed-scope and independent corroboration."""
from __future__ import annotations

import json

from document_agent.addition_evidence import verified_added_scope
from document_agent.db import connect
from document_agent.query_plan import plan_question


def _index(*, two_signed: bool = False, add_minutes: bool = True):
    conn = connect(":memory:")
    conn.execute("INSERT INTO documents(path,kind,status) VALUES"
                 "('Signed_Change_Order_CO12.pdf','pdf','ready')")
    document_id = conn.execute(
        "SELECT id FROM documents WHERE path='Signed_Change_Order_CO12.pdf'"
    ).fetchone()[0]
    source = "CO-12 authorizes 30 additional metres of cable tray in South Gallery."
    conn.execute(
        "INSERT INTO passages(document_id,page,chunk,text) VALUES(?,?,?,?)",
        (document_id, 1, 0, source))
    if two_signed:
        conn.execute(
            "INSERT INTO passages(document_id,page,chunk,text) VALUES(?,?,?,?)",
            (document_id, 2, 0, source))
    if add_minutes:
        conn.execute("INSERT INTO documents(path,kind,status) "
                     "VALUES('Site_Meeting_Minutes.docx','docx','ready')")
        minutes_id = conn.execute(
            "SELECT id FROM documents WHERE path='Site_Meeting_Minutes.docx'"
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO word_blocks(document_id,location,text) VALUES(?,?,?)",
            (minutes_id, "paragraph 3",
             "Participants reviewed CO-12: 30 metres extra South Gallery tray."))
    return conn


def test_signed_addition_uses_real_source_or_defers_if_not_unique():
    conn = _index()
    question = "What additional cable tray did the signed instruction add?"
    answer = verified_added_scope(conn, question, plan_question(conn, question))
    assert answer is not None
    assert answer.verification_status == "evidence_linked"
    assert answer.sources == ["Signed_Change_Order_CO12.pdf | page 1 | chunk 0"]
    assert "30 additional metres" in answer.text
    conn.close()
    duplicate = _index(two_signed=True)
    assert verified_added_scope(
        duplicate, question, plan_question(duplicate, question)) is None
    duplicate.close()


def test_two_original_sources_are_required_not_one_document_twice():
    conn = _index()
    question = "Which two sources confirm the South Gallery addition?"
    answer = verified_added_scope(conn, question, plan_question(conn, question))
    assert answer.sources == [
        "Signed_Change_Order_CO12.pdf | page 1 | chunk 0",
        "Site_Meeting_Minutes.docx | paragraph 3",
    ]
    conn.close()
    incomplete = _index(add_minutes=False)
    assert verified_added_scope(
        incomplete, question, plan_question(incomplete, question)) is None
    incomplete.close()


def test_signed_guard_does_not_take_over_financial_or_mixed_document_question():
    conn = _index()
    for question in (
        "What was the price of the signed cable tray addition?",
        "Did two sources authorize an additional contract price?",
        "What additional cable support did the unsigned proposal add?",
    ):
        assert verified_added_scope(
            conn, question, plan_question(conn, question)) is None
    conn.close()


def test_approved_boq_corroboration_requires_same_signed_change_order_id():
    conn = _index(add_minutes=False)
    conn.execute("INSERT INTO documents(path,kind,status) "
                 "VALUES('Costs.xlsx','xlsx','ready')")
    document_id = conn.execute(
        "SELECT id FROM documents WHERE path='Costs.xlsx'").fetchone()[0]
    payload = {
        "A": {"value": "CO13-1"},
        "B": {"value": "South Gallery extra cable tray"},
        "C": {"value": 30},
        "D": {"value": 450000},
    }
    conn.execute(
        "INSERT INTO sheet_rows(document_id,sheet,row_num,cells_json) "
        "VALUES(?,?,?,?)",
        (document_id, "Approved CO12", 2, json.dumps(payload)))
    question = "What additional cable tray did the signed instruction add?"
    incorrect = verified_added_scope(conn, question, plan_question(conn, question))
    assert incorrect.sources == ["Signed_Change_Order_CO12.pdf | page 1 | chunk 0"]

    payload["A"]["value"] = "CO12-1"
    conn.execute(
        "UPDATE sheet_rows SET cells_json=? "
        "WHERE document_id=? AND sheet='Approved CO12' AND row_num=2",
        (json.dumps(payload), document_id))
    correct = verified_added_scope(conn, question, plan_question(conn, question))
    assert correct.sources == [
        "Signed_Change_Order_CO12.pdf | page 1 | chunk 0",
        "Costs.xlsx | Approved CO12 | row 2",
    ]
    conn.close()
