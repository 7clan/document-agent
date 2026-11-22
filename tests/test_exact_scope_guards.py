"""Real application-entry tests for exact BOQ and failed-document scope guards."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

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


def test_frozen_release_documents_are_ingested_and_critical_items_resolve(tmp_path):
    """Exercise actual generated PDF/Word/Excel ingestion, not invented tool results."""
    project = Path(__file__).resolve().parents[1]
    corpus = tmp_path / "release_corpus"
    subprocess.run(
        [sys.executable, str(project / "scripts" / "create_release_corpus.py"),
         "--output", str(corpus)],
        check=True,
    )
    from document_agent.ingest import ingest_folder

    conn = connect(tmp_path / "release.db")
    report = ingest_folder(conn, str(corpus))
    assert not report.get("error")
    ready = conn.execute("SELECT COUNT(*) FROM documents WHERE status='ready'").fetchone()[0]
    failed = conn.execute("SELECT COUNT(*) FROM documents WHERE status!='ready'").fetchone()[0]
    assert ready == 8
    assert failed == 1

    checks = (
        ("Does HP-103 exceed SAR 1 million?", "No.", "Signed Base!F6"),
        ("Does HP-1030 exceed SAR 1 million?", "Yes.", "Signed Base!F10"),
    )
    for question, verdict, cell in checks:
        answer = ask(conn, question, provider="gemini")
        assert answer.text.startswith(verdict)
        assert len(answer.sources) == 1
        assert cell in answer.sources[0]
        assert answer.verification_status == "deterministically_verified"

    missing = ask(conn, "What amount belongs to exact item HP-999?",
                  provider="gemini")
    assert "No exact item HP-999" in missing.text
    assert "8400000" not in missing.text
    assert not missing.sources

    damaged = ask(conn, "Can the damaged attachment establish any new approval?",
                  provider="gemini")
    assert "09_Damaged_Attachment.pdf" in damaged.text
    assert "does NOT establish" in damaged.text
    assert not damaged.sources
    conn.close()
