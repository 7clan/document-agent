"""Independent generated-document A/B harness: retrieval, semantic claims and live QA.

Gold labels are fixed here before any candidate code change. The benchmark
imports a specified checkout's production modules; it does not modify answers.
Scores from anchored assertions are conservative proxies; raw answers are saved
for human review. Both checkouts use the same questions and generated files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

from docx import Document
from openpyxl import Workbook
from reportlab.pdfgen import canvas


def make_documents(folder: Path) -> None:
    def pdf(name, lines):
        obj = canvas.Canvas(str(folder / name), pagesize=(612, 792))
        for i, line in enumerate(lines):
            obj.drawString(35, 755 - i * 25, line)
        obj.save()

    pdf("Aurora_Executed_Agreement.pdf", [
        "FICTIONAL AURORA LIBRARY RETROFIT - EXECUTED AGREEMENT",
        "The architect handed the access drawings to the site contractor.",
        "The contractor must complete operational handover on 9 April 2029.",
        "Roof battery backup is excluded from the approved purchasing scope.",
        "Electrical works include four ventilation drives and a fire control panel.",
        "The signed agreement total is AED 4,800,000.",
        "A client-signed completion certificate is required for final acceptance.",
    ])
    pdf("Aurora_Unsigned_Addendum.pdf", [
        "FICTIONAL AURORA - UNSIGNED ADDENDUM AD-17",
        "A coordination draft suggests shifting handover to 3 May 2029.",
        "AD-17 has not been executed by either contracting party.",
        "The 9 April 2029 contractual handover deadline remains binding.",
        "Roof battery procurement remains excluded and not authorized.",
    ])
    pdf("Cedar_Inspection.pdf", [
        "FICTIONAL CEDAR BOOSTER STATION - INSPECTION RECORD",
        "Seven alarm loops were inspected on 12 August 2029.",
        "Loops AL-01 through AL-05 passed initial verification.",
        "Loops AL-06 and AL-07 failed and require another test.",
        "The owner has not issued a final signed acceptance certificate.",
        "Functional testing is not equivalent to formal owner acceptance.",
    ])
    pdf("Cedar_Damaged.pdf", ["This file must be overwritten"])
    (folder / "Cedar_Damaged.pdf").write_bytes(b"%PDF-1.7\ntruncated")

    minutes = Document()
    minutes.add_heading("Aurora coordination record", level=1)
    minutes.add_paragraph("On 21 March 2029, the team reviewed ventilation variation VO-22.")
    minutes.add_paragraph("VO-22 was approved for two extra ventilation drives.")
    minutes.add_paragraph("The contractor discussed purchasing roof batteries, but no signed instruction exists.")
    minutes.add_paragraph("The architect sent the revised wiring sketches to the electrician.")
    table = minutes.add_table(rows=1, cols=3)
    for c, value in zip(table.rows[0].cells, ("Activity", "Decision", "Date")):
        c.text = value
    for values in (
        ("Extra ventilation drives VO-22", "Approved", "21 March 2029"),
        ("Roof batteries", "Not authorized", "22 March 2029"),
    ):
        for c, value in zip(table.add_row().cells, values):
            c.text = value
    minutes.save(folder / "Aurora_Coordination.docx")

    log = Document()
    log.add_heading("Cedar field log", level=1)
    log.add_paragraph("The site electrician transferred the access badge to the safety officer.")
    log.add_paragraph("The backup pump is a suggested spare and has no purchase order.")
    log.add_paragraph("The owner requires correction of AL-06 and AL-07 before a final certificate.")
    log.save(folder / "Cedar_Field_Log.docx")

    workbook = Workbook()
    w = workbook.active
    w.title = "Authorized Items"
    w.append(["Code", "Package", "Quantity", "Extended Amount (AED)", "Status"])
    w.append(["AU-01", "Fire control panel", 1, 620000, "Approved"])
    w.append(["AU-02", "Ventilation drives", 4, 1380000, "Approved"])
    w.append(["AU-03", "Roof battery backup", 1, 950000, "Not authorized"])
    w.append(["AU-04", "Site finishing", 1, 420000, "Approved"])
    workbook.save(folder / "Aurora_Cost_Register.xlsx")

    workbook = Workbook()
    w = workbook.active
    w.title = "Cost Forecast"
    w.append(["Code", "Package", "Amount (AED)", "Classification"])
    w.append(["CE-11", "Alarm-loop rework", 165000, "Corrective"])
    w.append(["CE-12", "Backup pump", 780000, "Proposed"])
    w.append(["CE-13", "Valve assembly", 405000, "Committed"])
    workbook.save(folder / "Cedar_Budget.xlsx")


# Each source ID is manually labeled from the new, deterministic documents.
# A query tests semantic retrieval, not just exact keyword overlap.
RETRIEVAL = [
    ("What is the binding turnover day for the Aurora facility?",
     ["Aurora_Executed_Agreement.pdf | page 1 | chunk 0"]),
    ("Did the Aurora parties formally move the opening into May?",
     ["Aurora_Unsigned_Addendum.pdf | page 1 | chunk 0"]),
    ("Which optional energy system cannot be ordered under Aurora's agreement?",
     ["Aurora_Executed_Agreement.pdf | page 1 | chunk 0"]),
    ("Who originally passed the building access plans to the constructor?",
     ["Aurora_Executed_Agreement.pdf | page 1 | chunk 0"]),
    ("Which extra air-handling equipment received approval?",
     ["Aurora_Coordination.docx | paragraph 3"]),
    ("Did the meeting authorize energy storage purchasing?",
     ["Aurora_Coordination.docx | paragraph 4"]),
    ("Who supplied the updated electrical drawings?",
     ["Aurora_Coordination.docx | paragraph 5"]),
    ("How much does the approved fire protection panel cost?",
     ["Aurora_Cost_Register.xlsx | Authorized Items | row 2"]),
    ("What is the amount for code AU-02?",
     ["Aurora_Cost_Register.xlsx | Authorized Items | row 3"]),
    ("Which alarm circuits need another inspection?",
     ["Cedar_Inspection.pdf | page 1 | chunk 0"]),
    ("Can the Cedar operator claim final client sign-off?",
     ["Cedar_Inspection.pdf | page 1 | chunk 0"]),
    ("Who received the security access badge at Cedar?",
     ["Cedar_Field_Log.docx | paragraph 2"]),
    ("Has a binding order been raised for the standby pump?",
     ["Cedar_Field_Log.docx | paragraph 3"]),
    ("What is the projected spend on the suggested standby pump?",
     ["Cedar_Budget.xlsx | Cost Forecast | row 3"]),
    ("What is the committed valve assembly cost?",
     ["Cedar_Budget.xlsx | Cost Forecast | row 4"]),
]

# Positive/negative judgments have independently specified sources, claims,
# and exact indexed quotes. Deliberately avoid old release-corpus entities.
VERIFIER = [
    (True, "The architect handed the access drawings to the site contractor.",
     "Aurora_Executed_Agreement.pdf | page 1 | chunk 0",
     "The architect handed the access drawings to the site contractor."),
    (False, "The site contractor handed the access drawings to the architect.",
     "Aurora_Executed_Agreement.pdf | page 1 | chunk 0",
     "The architect handed the access drawings to the site contractor."),
    (False, "The architect handed the access drawings to the owner.",
     "Aurora_Executed_Agreement.pdf | page 1 | chunk 0",
     "The architect handed the access drawings to the site contractor."),
    (True, "The architect sent the revised wiring sketches to the electrician.",
     "Aurora_Coordination.docx | paragraph 5",
     "The architect sent the revised wiring sketches to the electrician."),
    (False, "The electrician sent the revised wiring sketches to the architect.",
     "Aurora_Coordination.docx | paragraph 5",
     "The architect sent the revised wiring sketches to the electrician."),
    (True, "The site electrician transferred the access badge to the safety officer.",
     "Cedar_Field_Log.docx | paragraph 2",
     "The site electrician transferred the access badge to the safety officer."),
    (False, "The safety officer transferred the access badge to the site electrician.",
     "Cedar_Field_Log.docx | paragraph 2",
     "The site electrician transferred the access badge to the safety officer."),
    (False, "The contractor must complete handover on 3 May 2029.",
     "Aurora_Unsigned_Addendum.pdf | page 1 | chunk 0",
     "A coordination draft suggests shifting handover to 3 May 2029."),
    (True, "The Aurora agreement total is AED 4,800,000.",
     "Aurora_Executed_Agreement.pdf | page 1 | chunk 0",
     "The signed agreement total is AED 4,800,000."),
    (False, "AU-03 is approved for purchasing.",
     "Aurora_Cost_Register.xlsx | Authorized Items | row 4", ""),
    (True, "AU-02 has an extended amount of AED 1,380,000.",
     "Aurora_Cost_Register.xlsx | Authorized Items | row 3", ""),
]

# Each case is evaluated for answer meaning AND cited location. Syntactic
# patterns intentionally allow paraphrases; every raw answer is preserved.
QA = [
    {"question": "When is the contractual Aurora handover, rather than the proposed later day?",
     "sources": ["Aurora_Executed_Agreement.pdf"], "required": [r"(?:9 April 2029|April 9,? 2029|2029-04-09)"],
     "forbidden": [r"(?:binding|contractual|approved)\s+(?:handover|date)[^\n.]{0,40}(?:3 May|May 3)"]},
    {"question": "Did AD-17 legitimately extend the Aurora completion date?",
     "sources": ["Aurora_Unsigned_Addendum.pdf"],
     "required": [r"(?:not\s+(?:signed|executed|approved)|un(?:signed|approved)|no\s+(?:approval|extension)|has\s+not\s+been\s+executed)"]},
    {"question": "How many Cedar alarm loops passed their initial inspection?",
     "sources": ["Cedar_Inspection.pdf"], "required": [r"\b(?:five|5)\b"]},
    {"question": "Which Cedar loops must be tested again?",
     "sources": ["Cedar_Inspection.pdf"],
     "required": [r"\bAL-06\b", r"\bAL-07\b"]},
    {"question": "Has Cedar received formal sign-off from its owner?",
     "sources": ["Cedar_Inspection.pdf"],
     "required": [r"(?:no\s+(?:final|signed|formal)|not\s+(?:issued|accepted|signed)|has\s+not|without\s+final|pending)"]},
    {"question": "What is the value of the Aurora fire control panel line item?",
     "sources": ["Aurora_Cost_Register.xlsx"],
     "required": [r"\b620,?000\b"]},
    {"question": "Can the team immediately purchase Aurora roof batteries on the existing authority?",
     "sources": ["Aurora_Executed_Agreement.pdf", "Aurora_Coordination.docx"],
     "required": [r"(?:not\s+(?:authorized|approved|permitted)|cannot|no\s+signed|excluded)"]},
    {"question": "What does the Cedar spare pump cost forecast say, and is it a binding order?",
     "sources": ["Cedar_Budget.xlsx", "Cedar_Field_Log.docx"],
     "required": [r"\b780,?000\b", r"(?:no\s+purchase\s+order|proposed|not\s+(?:approved|ordered|committed))"]},
    {"question": "Did the site contractor send the access drawings to the architect?",
     "sources": ["Aurora_Executed_Agreement.pdf"],
     "required": [r"(?:architect|contractor)", r"(?:not|rather|instead|architect\s+handed)"]},
]


def run(engine_root: Path, output: Path, provider: str, retrieval_mode: str) -> dict:
    sys.path.insert(0, str(engine_root / "src"))
    from document_agent.agent import ask, provider_error_diagnostic
    from document_agent.claim_verifier import validate_claims
    from document_agent.db import connect
    from document_agent.ingest import ingest_folder
    from document_agent.tools import get_evidence, search_documents

    with tempfile.TemporaryDirectory(prefix="unseen_ab_") as directory:
        folder = Path(directory) / "documents"
        folder.mkdir()
        make_documents(folder)
        digests = {
            x.name: hashlib.sha256(x.read_bytes()).hexdigest()
            for x in sorted(folder.iterdir()) if x.is_file()
        }
        conn = connect(Path(directory) / "index.db")
        result = {"engine": str(engine_root), "provider": provider,
                  "mode": retrieval_mode, "document_hashes": digests,
                  "retrieval": [], "verifier": [], "qa": []}
        try:
            result["ingest"] = ingest_folder(conn, folder)
            for question, gold in RETRIEVAL:
                try:
                    found = search_documents(conn, question, limit=5, mode=retrieval_mode)
                    labels = [x["citation"] for x in found.get("results", [])]
                    fallback = found.get("retrieval_mode") != retrieval_mode
                    result["retrieval"].append({
                        "question": question, "gold": gold, "found": labels,
                        "hit_at_5": any(x in labels for x in gold),
                        "recall_at_5": sum(x in labels for x in gold) / len(gold),
                        "mode": found.get("retrieval_mode"), "fallback": fallback,
                        "error": found.get("error"),
                    })
                except Exception as ex:  # noqa: BLE001 - benchmark records genuine failures
                    result["retrieval"].append({"question": question,
                                                "error": type(ex).__name__})
            for expected, claim, cite, quote in VERIFIER:
                payload = {"answer": claim, "insufficient": False,
                           "claims": [{"text": claim, "supports": [
                               {"citation": cite, "quote": quote}]}]}
                checked = validate_claims(conn, json.dumps(payload), [cite], claim)
                accepted = checked["claims"][0]["status"] != "unverified"
                result["verifier"].append({
                    "claim": claim, "gold_supported": expected, "accepted": accepted,
                    "correct": accepted == expected,
                    "reason": checked["claims"][0]["reason"],
                    "source_exists": "error" not in get_evidence(conn, cite),
                })
            if provider != "none":
                os.environ["DOCUMENT_AGENT_RETRIEVAL_MODE"] = retrieval_mode
                for gold in QA:
                    started = time.monotonic()
                    record = {"question": gold["question"],
                              "expected_source_files": gold["sources"]}
                    try:
                        answer = ask(conn, gold["question"], provider=provider)
                        cited = list(dict.fromkeys(answer.sources))
                        text = answer.text
                        found = [f for f in gold["sources"]
                                 if any(c.startswith(f + " | ") for c in cited)]
                        record.update({
                            "answer": text[:8000], "citations": cited,
                            "verification_status": answer.verification_status,
                            "source_coverage": len(found) / len(gold["sources"]),
                            "citations_resolve": bool(cited) and all(
                                "error" not in get_evidence(conn, cite) for cite in cited),
                            "semantic_anchor_match": all(
                                re.search(pattern, text, re.IGNORECASE) for pattern in gold["required"]),
                            "no_forbidden_assertion": not any(
                                re.search(pattern, text, re.IGNORECASE)
                                for pattern in gold.get("forbidden", [])),
                            "model_tool_calls": sum(
                                call.get("origin") != "application"
                                for call in answer.tool_calls),
                        })
                    except Exception as ex:  # noqa: BLE001 - benchmark records genuine failures
                        record["provider_error"] = provider_error_diagnostic(ex)
                        record["exception"] = type(ex).__name__
                    record["latency_seconds"] = round(time.monotonic()-started,2)
                    result["qa"].append(record)
                    # Provider exhaustion: stop before generating extra charges.
                    if record.get("provider_error", {}).get("http_status") in (402, 429):
                        break
            n = len(result["retrieval"])
            v = len(result["verifier"])
            answered = [r for r in result["qa"] if "provider_error" not in r]
            result["summary"] = {
                "documents": len(digests), "retrieval_cases": n,
                "retrieval_hit_at_5": sum(bool(r.get("hit_at_5")) for r in result["retrieval"]),
                "retrieval_fallback": sum(bool(r.get("fallback")) for r in result["retrieval"]),
                "verifier_cases": v,
                "verifier_correct": sum(r["correct"] for r in result["verifier"]),
                "verifier_false_accepts": sum(
                    r["accepted"] and not r["gold_supported"] for r in result["verifier"]),
                "verifier_false_rejects": sum(
                    not r["accepted"] and r["gold_supported"] for r in result["verifier"]),
                "qa_planned": len(QA), "qa_answered": len(answered),
                "qa_source_complete": sum(r.get("source_coverage") == 1 and
                                          r.get("citations_resolve") for r in answered),
                "qa_anchor_match": sum(bool(r.get("semantic_anchor_match")) and
                                       bool(r.get("no_forbidden_assertion"))
                                       for r in answered),
                "qa_both": sum(bool(r.get("semantic_anchor_match")) and
                               bool(r.get("no_forbidden_assertion")) and
                               r.get("source_coverage") == 1 and
                               bool(r.get("citations_resolve")) for r in answered),
                "qa_provider_errors": sum("provider_error" in r for r in result["qa"]),
                "note": "Anchor matching is an independent conservative proxy, "
                        "not full human semantic judgment; inspect preserved answers.",
            }
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8")
            print("UNSEEN_AB "+json.dumps(result["summary"]), flush=True)
            return result
        finally:
            conn.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--provider", choices=["none", "gemini", "compatible"], default="none")
    parser.add_argument("--mode", choices=["keyword", "hybrid"], default="keyword")
    args = parser.parse_args()
    run(args.engine_root.resolve(), args.output, args.provider, args.mode)


if __name__ == "__main__":
    main()
