"""Reproduce the six-document subtotal failure with hybrid retrieval enabled.

The original test documents were not committed. This synthetic reconstruction
preserves the recorded totals, sheet names and important original item values;
the remaining line values are test-only to reproduce the published subtotal.
"""
from __future__ import annotations

import io

import pytest
from docx import Document
from openpyxl import Workbook
from reportlab.pdfgen import canvas

from document_agent import hybrid
from document_agent.agent import _checked_financial_comparison, _verified_numeric_answer
from document_agent.db import connect
from document_agent.ingest import ingest_folder
from document_agent.spreadsheet import query_spreadsheet
from document_agent.tools import get_evidence, search_documents


class OfflineEncoder:
    """Test routing with controllable vectors, not real-model retrieval quality."""

    def encode(self, texts, **_kwargs):
        vectors = []
        for text in texts:
            lower = text.casefold()
            if any(word in lower for word in
                   ("completion", "deadline", "finalize", "finish")):
                vectors.append([1.0, 0.0, 0.0])
            elif any(word in lower for word in
                     ("transformer", "switchgear", "cable", "boq")):
                vectors.append([0.0, 1.0, 0.0])
            else:
                vectors.append([0.0, 0.0, 1.0])
        return vectors


def write_pdf(path, pages):
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    for lines in pages:
        for line_number, text in enumerate(lines):
            pdf.drawString(54, 760 - line_number * 18, text)
        pdf.showPage()
    pdf.save()
    path.write_bytes(buffer.getvalue())


@pytest.fixture
def six_document_index(tmp_path, monkeypatch):
    folder = tmp_path / "six_documents"
    folder.mkdir()
    write_pdf(folder / "01_Main_Contract.pdf", [
        ["Contractor shall finalize electrical construction works by 31 March 2027."],
        ["The original signed contract value is SAR 6,750,000.",
         "The selected items BOQ is not the complete original contract sum."],
    ])
    write_pdf(folder / "02_Approved_Change_Order_CO07.pdf", [
        ["Approved variation CO-07: additional 40m cable tray for Building B.",
         "The approved change order amount is SAR 320,000."],
    ])
    write_pdf(folder / "06_QA_Inspection_Report.pdf", [
        ["Four circuits passed inspection. Two circuits require retesting."],
    ])
    minutes = Document()
    minutes.add_paragraph("The approved change order is additional to the base scope.")
    minutes.save(folder / "03_Site_Meeting_Minutes.docx")

    workbook = Workbook()
    base = workbook.active
    base.title = "Electrical BOQ"
    base.append(["Item Code", "Description", "Qty", "Unit", "Unit Price (SAR)",
                 "Approved Amount (SAR)", "Status"])
    # Four original source-shape amounts and three synthetic remainder rows.
    # The seven base rows total exactly SAR 5,934,500.
    for item, description, total in [
        ("EL-101", "500 kVA transformers - Building A", 1_575_000),
        ("EL-102", "Switchgear panel SG-01", 1_240_000),
        ("EL-103", "Switchgear panel SG-02", 890_000),
        ("EL-104", "Cable installation and supports", 375_000),
        ("EL-105", "Control relay upgrades", 1_520_000),
        ("EL-106", "Electrical testing services", 200_000),
        ("EL-107", "Project closeout package", 134_500),
    ]:
        base.append([item, description, 1, "ea", total, total, "Base contract"])
    variation = workbook.create_sheet("Change Order BOQ")
    variation.append(["Item Code", "Description", "Qty", "Unit",
                      "Unit Price (SAR)", "Approved Amount (SAR)", "Status"])
    variation.append(["CO-07-B", "Cable tray - Building B", 40, "m",
                      8_000, 320_000, "Approved"])
    workbook.save(folder / "04_Electrical_BOQ.xlsx")

    schedule = Workbook()
    milestones = schedule.active
    milestones.title = "Milestones"
    milestones.append(["ID", "Event", "Date", "Classification"])
    milestones.append(["M-01", "Design approval", "2026-11-20", "Contractual"])
    milestones.append(["M-02", "Materials delivery", "2026-12-10", "Contractual"])
    schedule.save(folder / "05_Project_Schedule.xlsx")

    conn = connect(tmp_path / "index.sqlite")
    report = ingest_folder(conn, folder)
    assert report["indexed"] == 6 and report["failed"] == 0
    monkeypatch.setenv("DOCUMENT_AGENT_RETRIEVAL_MODE", "hybrid")
    monkeypatch.setattr(hybrid, "embedding_model", OfflineEncoder)
    yield conn
    conn.close()


def test_replay_failed_original_sum_without_mixing_change_order(six_document_index):
    conn = six_document_index
    source = query_spreadsheet(
        conn, file="04_Electrical_BOQ.xlsx", sheet="Electrical BOQ",
        operator="all", value=0, currency="SAR",
    )
    extra = query_spreadsheet(
        conn, file="04_Electrical_BOQ.xlsx", sheet="Change Order BOQ",
        operator="all", value=0, currency="SAR",
    )
    assert source["total_matches"] == 7
    assert source["matched_amount_sums"] == {"SAR": "5934500"}
    assert extra["matched_amount_sums"] == {"SAR": "320000"}

    question = "Does the selected-items BOQ subtotal equal the complete original contract sum?"
    answer = _checked_financial_comparison(
        conn, question, [{"name": "search_documents", "ok": True}],
    )
    assert answer is not None, "Unable to select original BOQ and contract value"
    assert answer.text.startswith("No.")
    assert answer.structured["boq_subtotal"] == "5934500"
    assert answer.structured["contract_value"] == "6750000"
    assert answer.structured["boq_sheet"] == "Electrical BOQ"
    assert answer.verification_status == "evidence_linked"
    assert len([cite for cite in answer.sources
                if "Electrical BOQ!F" in cite]) == 7
    assert "04_Electrical_BOQ.xlsx | Change Order BOQ!F2" not in answer.sources
    assert "01_Main_Contract.pdf | page 2 | chunk 0" in answer.sources
    assert answer.tool_calls[-1]["origin"] == "application"
    assert answer.tool_calls[-1]["arithmetic_checked"] is True


def test_replay_el103_threshold_uses_exact_original_cell(six_document_index):
    conn = six_document_index
    result = _verified_numeric_answer(
        conn,
        "Does item EL-103 exceed SAR 1,000,000?",
        {"file": "04_Electrical_BOQ.xlsx", "sheet": "Electrical BOQ",
         "operator": "gt", "value": 1_000_000, "currency": "SAR"},
        [{"name": "query_spreadsheet", "ok": True}],
    )
    assert result.text.startswith("No. Item EL-103 is SAR 890000")
    assert result.sources == ["04_Electrical_BOQ.xlsx | Electrical BOQ!F4"]
    assert result.verification_status == "deterministically_verified"


def test_hybrid_paraphrase_resolves_original_pdf_source(six_document_index):
    conn = six_document_index
    question = "When is the completion deadline?"
    answer = search_documents(conn, question, limit=8, mode="hybrid")
    assert answer["retrieval_mode"] == "hybrid"
    target = "01_Main_Contract.pdf | page 1 | chunk 0"
    assert target in [hit["citation"] for hit in answer["results"]]
    original = get_evidence(conn, target)
    assert "finalize electrical construction works" in original["text"]
