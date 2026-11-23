"""Source-authenticated procurement authorization checks (no provider/API calls)."""
from __future__ import annotations

from document_agent.agent import ask
from document_agent.db import connect
from document_agent.optional_procurement import verified_optional_procurement
from document_agent.query_plan import plan_question


QUESTION = "Can the optional energy store be ordered under the signed papers?"


def _db(*, pending_text: str | None = None, second_pending: bool = False):
    conn = connect(":memory:")
    entries = [
        ("Signed_Project_Contract.pdf",
         ("Civil excavation and Phase 2 battery storage are excluded. "
          "Phase 2 battery storage is an optional future package, "
          "not authorized procurement.")),
        ("Signed_Change_Order_CO12.pdf",
         "CO-12 does not authorize Phase 2 battery storage."),
        ("Pending_Change_Request_CR13.pdf",
         pending_text if pending_text is not None else
         "The client has not approved or signed CR-13. "
         "CR-13 requests a Phase 2 battery procurement decision; it remains open."),
    ]
    if second_pending:
        entries.append(("Pending_Change_Request_CR14.pdf",
                        ("CR-14 requests a Phase 2 battery procurement decision; "
                         "it remains open.")))
    for name, content in entries:
        conn.execute("INSERT INTO documents(path,kind,status) "
                     "VALUES(?, 'pdf', 'ready')", (name,))
        doc_id = conn.execute("SELECT id FROM documents WHERE path=?", (name,)).fetchone()[0]
        conn.execute("INSERT INTO passages(document_id,page,chunk,text) "
                     "VALUES(?,1,0,?)", (doc_id, content))
    return conn


def test_distinct_signed_and_pending_sources_required_and_resolved(monkeypatch):
    conn = _db()

    def no_provider(*_args, **_kwargs):
        raise AssertionError("Explicit negative authorization must not use model")

    monkeypatch.setattr("document_agent.agent._ask_gemini", no_provider)
    response = ask(conn, QUESTION, provider="gemini")
    assert response.text.startswith("No.")
    assert "does not authorize" in response.text
    assert "remains open" in response.text
    assert response.sources == [
        "Signed_Project_Contract.pdf | page 1 | chunk 0",
        "Signed_Change_Order_CO12.pdf | page 1 | chunk 0",
        "Pending_Change_Request_CR13.pdf | page 1 | chunk 0",
    ]
    assert response.verification_status == "evidence_linked"
    assert response.tool_calls[1]["name"] == "host_optional_procurement_evidence"
    conn.close()


def test_pending_approval_cannot_be_inferred_from_unrelated_material():
    conn = _db(pending_text="CR-13 requests a Phase 2 battery decision. "
               "A different project proposal remains open.")
    assert verified_optional_procurement(
        conn, QUESTION, plan_question(conn, QUESTION)) is None
    conn.close()


def test_different_phase_must_not_be_mistaken_for_pending_decision():
    conn = _db(pending_text="CR-13 requests a Phase 3 battery procurement decision; "
               "it remains open.")
    assert verified_optional_procurement(
        conn, QUESTION, plan_question(conn, QUESTION)) is None
    conn.close()


def test_multiple_pending_requests_require_interpretation():
    conn = _db(second_pending=True)
    assert verified_optional_procurement(
        conn, QUESTION, plan_question(conn, QUESTION)) is None
    conn.close()


def test_unrelated_optional_material_is_not_false_denied():
    conn = _db()
    question = "Can the optional solar inverter be ordered under signed papers?"
    assert verified_optional_procurement(
        conn, question, plan_question(conn, question)) is None
    conn.close()
