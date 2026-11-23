"""Produce a comparison from actual browser-recording JSON, not synthetic scores."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def pct(n: int, total: int) -> str:
    return f"{n}/{total} ({100 * n / total:.1f}%)" if total else "N/A"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    reports = {}
    for name, p in (("main", args.baseline), ("candidate", args.candidate)):
        if not p.is_file():
            reports[name] = None
        else:
            reports[name] = json.loads(p.read_text(encoding="utf-8"))
    a, b = reports["main"], reports["candidate"]
    hashes_equal = bool(
        a and b and a["ground_truth_sha256"] == b["ground_truth_sha256"]
        and a["document_hashes"] == b["document_hashes"]
        and a["model"] == b["model"])
    rows = []
    if a and b:
        for baseline_case, candidate_case in zip(a["cases"], b["cases"]):
            if (baseline_case["id"] != candidate_case["id"]
                    or baseline_case["question"] != candidate_case["question"]
                    or baseline_case["expected_answer"] != candidate_case["expected_answer"]):
                raise ValueError("The answers are not paired against the same frozen questions")
            rows.append({
                "id": baseline_case["id"],
                "critical": baseline_case["critical"],
                "category": baseline_case["category"],
                "question": baseline_case["question"],
                "expected_answer": baseline_case["expected_answer"],
                "expected_sources": " ; ".join(baseline_case["expected_citations"]),
                "main_answer": baseline_case.get("displayed_answer", ""),
                "new_answer": candidate_case.get("displayed_answer", ""),
                "main_citations": " ; ".join(baseline_case.get("citations", [])),
                "new_citations": " ; ".join(candidate_case.get("citations", [])),
                "main_source_coverage": baseline_case.get(
                    "all_expected_sources_covered", False),
                "new_source_coverage": candidate_case.get(
                    "all_expected_sources_covered", False),
                "main_sources_resolve": baseline_case.get("all_sources_resolve", False),
                "new_sources_resolve": candidate_case.get("all_sources_resolve", False),
                "main_error": json.dumps(baseline_case.get("error")),
                "new_error": json.dumps(candidate_case.get("error")),
            })
    if rows:
        with (args.output / "all_44_paired_answers.csv").open(
                "w", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(file, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    lines = [
        "# Full final interview: original main vs newest claim-hardening",
        "",
        "## Provenance and fair comparison",
        "",
        f"- Identical frozen question/document hashes and provider/model: **{hashes_equal}**",
        f"- Original main commit: `{a['engine_sha'] if a else 'no recording'}`",
        f"- Candidate commit: `{b['engine_sha'] if b else 'no recording'}`",
        f"- Same provider: **{a['model'] if a else 'N/A'}** through OpenRouter.",
        "- Unmodified original Streamlit apps; both sessions are uncut browser recordings.",
        "- Model replies are **real**. Citation existence and labeled source recall "
        "do **not** imply factual correctness.",
        "- Any incomplete recording or 402/429 is a recorded failure, never a success.",
        "",
        "## Measured outcomes",
        "",
        "| Metric | Current main | Newest PR #9 |",
        "|---|---:|---:|",
    ]
    fields = [
        ("Answers observed", "completed_with_answer"),
        ("Questions with citations", "source_linked"),
        ("Answers with validated source IDs", "all_retrieved_sources_resolve"),
        ("All expected sources supplied", "all_expected_sources_present"),
        ("Required source completeness", "evidence_required_covered"),
        ("Critical cases with all expected sources", "critical_evidence_covered"),
        ("Browser/execution errors", "errors"),
    ]
    for label, key in fields:
        left = a["summary"].get(key) if a else "N/A"
        right = b["summary"].get(key) if b else "N/A"
        lines.append(f"| {label} | {left} | {right} |")
    lines.extend([
        "", "## Evidence videos",
        "",
        "- `main/full_uncut_interview.webm` (and MP4, if encoding succeeded)",
        "- `candidate/full_uncut_interview.webm` (and MP4, if encoding succeeded)",
        "- Original per-question source citations and displayed answers are in "
        "`main/browser_results.json` and `candidate/browser_results.json`.",
        "",
        "## Full-answer correctness requires reading the actual answers",
        "",
        "Automated citation checks are source *coverage* checks, not semantic "
        "entailment checks. The full 44-answer transcript is saved alongside the "
        "uncut videos for independent source-by-source grading.",
        "",
        "## Case-level source differences",
        "",
        "| ID | Critical | Main cited every labeled source | Candidate cited every labeled source |",
        "|---|---|---|---|",
    ])
    for case in rows:
        lines.append(
            f"| {case['id']} | {'Yes' if case['critical'] else 'No'} "
            f"| {'Yes' if case['main_source_coverage'] else 'No'} "
            f"| {'Yes' if case['new_source_coverage'] else 'No'} |")
    if not a or not b:
        lines.append("\n**Partial comparison only:** at least one browser report is missing.")
    (args.output / "COMPARISON.md").write_text("\n".join(lines) + "\n",
                                                 encoding="utf-8")
    print("PAIR_REPORT", json.dumps({
        "hashes_match": hashes_equal,
        "main": a["summary"] if a else None,
        "candidate": b["summary"] if b else None,
        "paired_count": len(rows),
    }), flush=True)
    return 0 if hashes_equal and len(rows) == 44 else 1


if __name__ == "__main__":
    raise SystemExit(main())
