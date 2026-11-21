"""Measure retrieval rankings against human-labeled citation locations.

This evaluates *retrieval*, not the accuracy of the final LLM answer. No model
or document is downloaded; only an explicitly enabled local embedding model is
used for hybrid mode. Use --demo for a synthetic corpus or --db/--cases for a
locally indexed, separately labeled document collection.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from time import perf_counter
from typing import Any

from document_agent.db import connect
from document_agent.tools import search_documents


def demo_database() -> sqlite3.Connection:
    """Generate an entirely fictional, source-cited mixed-format index."""
    conn = connect(":memory:")
    for path, kind in (
        ("Contract.pdf", "pdf"), ("CO07.pdf", "pdf"), ("BOQ.xlsx", "xlsx"),
        ("Minutes.docx", "docx"), ("QA.pdf", "pdf"),
    ):
        conn.execute(
            "INSERT INTO documents(path,kind,status) VALUES(?,?,'ready')",
            (path, kind),
        )
    ids = {
        row["path"]: row["id"] for row in conn.execute("SELECT id,path FROM documents")
    }
    for path, page, text in (
        ("Contract.pdf", 1, ("The contractual final commissioning and handover "
         "deadline is 31 March 2027. IFC drawings are due 20 November 2026.")),
        ("Contract.pdf", 2, ("Phase 2 battery storage is a proposal only and "
         "requires signed approval for procurement.")),
        ("CO07.pdf", 1, ("Approved change order CO-07 adds 40 metres of cable tray "
         "in Building B. The revised contract sum is SAR 7,070,000.")),
        ("QA.pdf", 1, ("Circuits C-05 and C-06 require retesting. A formal final "
         "acceptance certificate has not been issued.")),
    ):
        conn.execute(
            "INSERT INTO passages(document_id,page,chunk,text) VALUES(?,?,0,?)",
            (ids[path], page, text),
        )
    conn.execute(
        "INSERT INTO word_blocks(document_id,ordinal,kind,location,section,text) "
        "VALUES(?,?,?,?,?,?)",
        (ids["Minutes.docx"], 1, "paragraph", "paragraph 1", "",
         "The proposed handover on 5 April 2027 remains unapproved."),
    )
    for number, item, amount in (
        (2, "EL-103 Switchgear panel SG-02", 890000),
        (3, "EL-1030 Large transformer", 2400000),
        (4, "EL-101 Distribution transformer", 1575000),
    ):
        cells = {
            "A": {"value": item}, "B": {"value": amount}, "C": {"value": "SAR"}
        }
        conn.execute(
            "INSERT INTO sheet_rows(document_id,sheet,row_num,cells_json) "
            "VALUES(?,?,?,?)",
            (ids["BOQ.xlsx"], "Items", number, json.dumps(cells)),
        )
    conn.commit()
    return conn


def demo_cases() -> list[dict[str, Any]]:
    """Gold citations are manually labeled against demo_database()."""
    return [
        {"query": "What is the price for EL-103?",
         "expected_citations": ["BOQ.xlsx | Items | row 2"]},
        {"query": "How much is EL-1030?",
         "expected_citations": ["BOQ.xlsx | Items | row 3"]},
        {"query": "Compare items EL-103 and EL-1030",
         "expected_citations": ["BOQ.xlsx | Items | row 2",
                                "BOQ.xlsx | Items | row 3"]},
        {"query": "What changed in CO-07?",
         "expected_citations": ["CO07.pdf | page 1 | chunk 0"]},
        {"query": "When must the project reach final commissioning?",
         "expected_citations": ["Contract.pdf | page 1 | chunk 0"]},
        {"query": "Was the proposed handover date approved?",
         "expected_citations": ["Minutes.docx | paragraph 1"]},
        {"query": "Which electrical circuits require another inspection?",
         "expected_citations": ["QA.pdf | page 1 | chunk 0"]},
        {"query": "Has a final acceptance certificate been issued?",
         "expected_citations": ["QA.pdf | page 1 | chunk 0"]},
    ]


def read_cases(path: Path) -> list[dict[str, Any]]:
    cases = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        raise ValueError("Evaluation cases must be a nonempty JSON list")
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("query"), str):
            raise TypeError("Each case needs a question string under 'query'")
        citations = case.get("expected_citations")
        if not isinstance(citations, list) or not citations or not all(
            isinstance(value, str) and value for value in citations
        ):
            raise ValueError("Each case needs a nonempty expected_citations list")
        if "file" in case and not isinstance(case["file"], str):
            raise ValueError("Optional file filter must be a filename")
    return cases


def evaluate(
    conn: sqlite3.Connection, cases: list[dict[str, Any]],
    *, mode: str, k: int,
) -> dict[str, Any]:
    """Compute citation Recall@k, Hit@k and MRR@k; flag fallback explicitly."""
    if not cases or k < 1:
        raise ValueError("Provide at least one case and k >= 1")
    details = []
    total_recall = total_hits = total_rr = 0.0
    fallback_cases = 0
    for case in cases:
        started = perf_counter()
        result = search_documents(
            conn, case["query"], limit=k, file=case.get("file", ""), mode=mode
        )
        elapsed = round((perf_counter() - started) * 1000, 2)
        if "error" in result:
            raise ValueError(f"Search failed: {result['error']}")
        actual_mode = result.get("retrieval_mode", "keyword")
        if mode == "hybrid" and actual_mode != "hybrid":
            fallback_cases += 1
        returned = [hit["citation"] for hit in result["results"]]
        expected = set(case["expected_citations"])
        found = expected.intersection(returned)
        reciprocal_rank = next(
            (1 / rank for rank, citation in enumerate(returned, start=1)
             if citation in expected), 0.0
        )
        recall = len(found) / len(expected)
        hit = bool(found)
        total_recall += recall
        total_hits += int(hit)
        total_rr += reciprocal_rank
        details.append({
            "query": case["query"], "expected_citations": sorted(expected),
            "retrieved_citations": returned, "recall_at_k": round(recall, 4),
            "hit_at_k": hit, "reciprocal_rank": round(reciprocal_rank, 4),
            "actual_mode": actual_mode, "latency_ms": elapsed,
            "warning": result.get("retrieval_warning"),
        })
    n = len(cases)
    return {
        "requested_mode": mode, "k": k, "cases": n,
        "valid_for_mode": not (mode == "hybrid" and fallback_cases),
        "fallback_cases": fallback_cases,
        "mean_recall_at_k": round(total_recall / n, 4),
        "hit_rate_at_k": round(total_hits / n, 4),
        "mrr_at_k": round(total_rr / n, 4),
        "details": details,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true",
                        help="Use a generated, fictional and labeled document index")
    parser.add_argument("--db", type=Path, help="Existing SQLite document index")
    parser.add_argument("--cases", type=Path,
                        help="JSON list with query and expected_citations")
    parser.add_argument("--mode", choices=("keyword", "hybrid", "both"), default="both")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--output", type=Path, help="Save JSON results locally")
    args = parser.parse_args()
    if args.demo:
        if args.db or args.cases:
            parser.error("--demo cannot be combined with --db or --cases")
        conn, cases = demo_database(), demo_cases()
    else:
        if not args.db or not args.cases or not args.db.is_file():
            parser.error("Supply an existing --db and a --cases JSON file, or --demo")
        conn, cases = connect(args.db), read_cases(args.cases)
    try:
        modes = ("keyword", "hybrid") if args.mode == "both" else (args.mode,)
        reports = {mode: evaluate(conn, cases, mode=mode, k=args.k) for mode in modes}
    finally:
        conn.close()
    # The report contains question text and citations: protect it for real datasets.
    output = {"dataset": "fictional demo" if args.demo else "user-labeled local index",
              "reports": reports}
    rendered = json.dumps(output, indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if any(not report["valid_for_mode"] for report in reports.values()):
        print("Hybrid metrics invalid: semantic retrieval fell back to keyword.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
