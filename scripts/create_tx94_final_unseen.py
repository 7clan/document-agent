"""Create a previously unseen, self-contained fictional transit signalling dossier.

This is a fresh comparison corpus, not AQ-73 or MQ-46. The original
answering applications are checked out from pinned SHAs and never receive
the holdout rubric. Eight documents index and one annex is intentionally
unreadable, to expose coverage notices without changing the question key.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from docx import Document
from openpyxl import Workbook
from reportlab.pdfgen import canvas


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.output.resolve()
    if root.exists() and any(root.iterdir()):
        parser.error("Output directory must be empty to preserve a frozen corpus")
    root.mkdir(parents=True, exist_ok=True)

    def make_pdf(name: str, pages: list[list[str]]) -> None:
        document = canvas.Canvas(str(root / name), pagesize=(612, 792))
        for page in pages:
            y = 745
            for line in page:
                if len(line) > 108:
                    raise ValueError(f"PDF line too long in {name}: {line}")
                document.drawString(35, y, line)
                y -= 22
            document.showPage()
        document.save()

    make_pdf("01_TX94_Executed_Agreement.pdf", [[
        "FICTIONAL PROJECT TX-94 | ASTERLINE TRANSIT SENSOR RENEWAL",
        "Executed 14 February 2029 by Asterline Transit Authority and Vale Circuitworks.",
        "Install twelve 24 VDC platform-safety sensors PS-01 through PS-12.",
        "Install six remote signal cabinets at North Loop and Harbor Junction.",
        "Supply three kilometres of shielded fibre-optic communications cable.",
        "Provide supervisory dashboard integration and weatherproof enclosures.",
        "Optional AI video analytics and drone inspections are excluded.",
        "The executed original complete contract value is EUR 6,480,000.",
        "Holdback is five percent of the approved total at final acceptance.",
    ], [
        "TX-94 | CONTRACTUAL SCHEDULE AND ACCEPTANCE",
        "Baseline design packages due 18 May 2029.",
        "Electrical commissioning checks due 31 August 2029.",
        "Binding signed contractual handover: 28 November 2029.",
        "Formal acceptance requires a written System Acceptance Certificate",
        "signed by the Chief Systems Assurance Officer of Asterline Transit Authority.",
        "Passing subsystem tests does not constitute contractual acceptance.",
        "Selected BOQ worksheets are partial and exclude service overhead.",
    ]])

    make_pdf("02_TX94_Signed_Change_V17.pdf", [[
        "TX-94 | SIGNED VARIATION V-17 | 9 APRIL 2029",
        "V-17 authorizes fourteen stainless mounting brackets for signal cabinets",
        "on the East Viaduct platform access corridor.",
        "Approved incremental cost: EUR 180,000.",
        "The revised authorized full contract value is EUR 6,660,000.",
        "V-17 does not approve optional AI video analytics.",
        "V-17 leaves the contractual 28 November 2029 handover unchanged.",
    ]])

    make_pdf("03_TX94_Unsigned_Proposal_CR23.pdf", [[
        "TX-94 | CHANGE REQUEST CR-23 | UNSIGNED DRAFT",
        "Supplier requests an optional AI video analytics subscription.",
        "The unapproved proposed additional price is EUR 240,000.",
        "CR-23 also proposes shifting contractual handover to 12 December 2029.",
        "No client signature exists and no purchase authorization was issued.",
        "CR-23 has no authority to change the signed 28 November 2029 deadline.",
    ]])

    make_pdf("06_TX94_QA_Field_Checks.pdf", [[
        "TX-94 | QUALITY ASSURANCE FIELD CHECKS | 21 OCTOBER 2029",
        "Of eighteen recorded safety interlock checks, fifteen passed.",
        "Three failed checks: PS-04, PS-09 and PS-12 need recalibration.",
        "These three sensor tests require retesting and acceptance signoff.",
        "No System Acceptance Certificate has yet been signed or issued.",
        "Successful partial inspections do not prove final client acceptance.",
    ]])

    make_pdf("08_TX94_Issues_and_Risks.pdf", [[
        "TX-94 | SITE ISSUES REGISTER | STATUS 22 OCTOBER 2029",
        "R-11: Access permissions for East Viaduct cable pulling are approved.",
        "R-12: Three interlock sensor failures remain open pending recalibration.",
        "R-13: Optional AI analytics approval remains pending; NOT procured.",
        "No accepted instruction supersedes the signed contract or V-17.",
    ]])

    (root / "09_TX94_Corrupt_Appendix.pdf").write_bytes(
        b"%PDF-1.7\ntruncated by design; no xref and no valid page structure\n"
    )

    docx = Document()
    docx.add_heading("TX-94 | Commissioning coordination minutes", level=1)
    for line in (
        "Meeting recorded on 2 November 2029.",
        "The internal readiness estimate is 18 November 2029; this is a planning forecast.",
        "The signed contractual handover remains 28 November 2029.",
        "The 12 December 2029 date is merely an unsigned proposal in CR-23.",
        "The Chief Systems Assurance Officer must sign the System Acceptance Certificate.",
        "Three failed sensor interlock checks remain open.",
    ):
        docx.add_paragraph(line)
    table = docx.add_table(rows=1, cols=3)
    for cell, value in zip(table.rows[0].cells,
                           ("Milestone", "Date", "Authority")):
        cell.text = value
    for values in (
        ("Internal readiness", "18 November 2029", "Planning only"),
        ("Contract handover", "28 November 2029", "Signed and binding"),
        ("CR-23 handover request", "12 December 2029", "Unsigned; not approved"),
    ):
        new = table.add_row()
        for cell, value in zip(new.cells, values):
            cell.text = value
    docx.save(root / "04_TX94_Coordination_Minutes.docx")

    book = Workbook()
    sheet = book.active
    sheet.title = "Selected Signed BOQ"
    sheet.append(["Partial base cost sheet; services and overhead are not included"])
    sheet.append([])
    sheet.append(["Ref", "Description", "Quantity", "Unit", "Unit EUR", "Amount EUR"])
    for row in (
        ("RS-101", "12 platform safety sensors", 12, "each", 97500, 1170000),
        ("RS-102", "Six remote signal cabinets", 6, "each", 215000, 1290000),
        ("RS-103", "Shielded fibre-optic backbone", 3000, "m", 400, 1200000),
        ("RS-104", "SCADA dashboard integration", 1, "lot", 1790000, 1790000),
        ("RS-105", "Electrical commissioning", 1, "lot", 660000, 660000),
        ("Subtotal", "Selected base equipment only", None, None, None, 6110000),
    ):
        sheet.append(row)
    approved = book.create_sheet("Signed Variation V17")
    approved.append(["Ref", "Description", "Quantity", "Unit", "Unit EUR", "Amount EUR"])
    approved.append(["V17-A", "East Viaduct mounting brackets", 14, "each", 12857.142857, 180000])
    pending = book.create_sheet("Pending CR23")
    pending.append(["Ref", "Description", "Quantity", "Unit", "Unit EUR", "Amount EUR"])
    pending.append(["CR23-A", "Unsigned optional AI analytics", 1, "lot", 240000, 240000])
    book.save(root / "05_TX94_Partial_Cost_Book.xlsx")

    schedule = Workbook()
    sh = schedule.active
    sh.title = "Schedule"
    sh.append(["ID", "Milestone", "Date", "Classification", "Approval"])
    for row in (
        ("T-01", "Design packages", "2029-05-18", "Contractual", "Signed agreement"),
        ("T-02", "Electrical commissioning", "2029-08-31", "Contractual", "Signed agreement"),
        ("T-03", "Final handover", "2029-11-28", "Contractual", "Signed agreement"),
        ("T-04", "Internal readiness", "2029-11-18", "Internal", "Planning only"),
        ("T-05", "CR-23 requested handover", "2029-12-12", "Proposal", "Not approved"),
    ):
        sh.append(row)
    schedule.save(root / "07_TX94_Schedule.xlsx")

    assert len(list(root.iterdir())) == 9
    print("FRESH_TX94_DOCUMENTS_CREATED 8 readable 1 intentionally corrupt",
          flush=True)


if __name__ == "__main__":
    main()
