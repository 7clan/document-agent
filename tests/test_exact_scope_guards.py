"""Real application-entry tests for exact BOQ and failed-document scope guards."""
from __future__ import annotations

import json

from document_agent.agent import ask
from document_agent.db import connect


def _book():
    conn = connect(":memory:")
    conn.execute(
        "INSERT INTO documents(path,kind,status) VALUES"
        "('BOQ.xlsx','xlsx','ready'),"
        "('Damaged.pdf','pdf','failed')"
    )
    records = [
        (2, {"A": {"value": "Item ID"}, "B": {"value": "Total Amount (SAR)"}}),
        (4, {"A": {"value": "HP-103"}, "B": {"value": 950000}}),
        (5, {"A": {"value": "HP-1030"}, "B": {"value": 1050000}}),
        (6, {"A": {"value": "HP-104"}, "B": {"value": 8400000}}),
    ]
    doc_id = conn.execute("SELECT id FROM documents WHERE path='BOQ.xlsx'").fetchone()[0]
    for row, cells in records:
        conn.execute(
            "INSERT INTO sheet_rows(document_id,sheet,row_num,cells_json)"
            " VALUES(?,?,?,?)",
            (doc_id, "Signed Base", row, json.dumps(cells)),
        )
    conn.commit()
    return conn


def test_exact_threshold_comparison_uses_original_cells_without_provider(monkeypatch):
    conn = _book()

    def provider_must_not_run(*_args, **_kwargs):
        raise AssertionError("Deterministic exact-item request must not reach a provider")

    monkeypatch.setattr("document_agent.agent._ask_gemini", provider_must_not_run)
    below = ask(conn, "Does HP-103 exceed SAR 1 million?", provider="gemini")
    above = ask(conn, "Does HP-1030 exceed SAR 1 million?", provider="gemini")
    assert below.text.startswith("No. ")
    assert above.text.startswith("Yes. ")
    assert "950000" in below.text and "1050000" not in below.text
    assert "1050000" in above.text and "950000" not in above.text
    assert below.sources == ["BOQ.xlsx | Signed Base!B4"]
    assert above.sources == ["BOQ.xlsx | Signed Base!B5"]
    assert below.verification_status == "deterministically_verified"
    assert above.verification_status == "deterministically_verified"
    assert any(event["name"] == "host_exact_item_query" for event in above.tool_calls)
    conn.close()


def test_nonexistent_exact_identifier_never_returns_an_unrelated_total():
    conn = _book()
    answer = ask(conn, "What amount belongs to exact item HP-999?", provider="gemini")
    assert "No exact item HP-999" in answer.text
    assert "8400000" not in answer.text and "8,400,000" not in answer.text
    assert not answer.sources
    assert answer.verification_status == "unverified"
    conn.close()


def test_exact_item_amount_without_threshold_reports_only_its_own_value():
    conn = _book()
    answer = ask(conn, "What is the amount of item HP-103?", provider="gemini")
    assert "950000" in answer.text
    assert "1050000" not in answer.text
    assert "8400000" not in answer.text
    assert answer.sources == ["BOQ.xlsx | Signed Base!B4"]
    conn.close()


def test_damaged_attachment_does_not_inherit_approval_from_other_documents():
    conn = _book()
    conn.execute("INSERT INTO documents(path,kind,status) "
                 "VALUES('Signed_Approval.pdf','pdf','ready')")
    doc = conn.execute("SELECT id FROM documents "
                       "WHERE path='Signed_Approval.pdf'").fetchone()[0]
    conn.execute("INSERT INTO passages(document_id,page,chunk,text) VALUES"
                 "(?,?,?,?)", (doc, 1, 0, "Approved and signed."))
    answer = ask(conn, "Can the damaged attachment establish any new approval?",
                 provider="gemini")
    assert "Damaged.pdf" in answer.text
    assert "unavailable" in answer.text
    assert "could not" not in answer.text or "content" in answer.text
    assert "Signed_Approval.pdf" not in answer.text
    assert not answer.sources
    assert answer.verification_status == "unverified"
    assert any(event["name"] == "host_unreadable_attachment"
               for event in answer.tool_calls)
    conn.close()
