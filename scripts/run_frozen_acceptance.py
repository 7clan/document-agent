"""Replay the *unchanged* 44-case ground truth through the real application.

No stubs, injected answers, renamed cases or substituted provider calls.
Raw model answers, citation resolution and a compact tool audit are preserved
for independent review. Source coverage is NOT a semantic-correctness score.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from document_agent.agent import ask, provider_error_diagnostic
from document_agent.db import connect
from document_agent.ingest import ingest_folder
from document_agent.tools import get_evidence

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "evaluation" / "release_candidate_ground_truth.json"


def _citation_matches(label: str, actual: str) -> bool:
    if label == actual:
        return True
    row = re.fullmatch(r"(.+?) \| (.+?) \| row (\d+)", label)
    cell = re.fullmatch(r"(.+?) \| (.+?)!([A-Z]{1,3})(\d+)", actual)
    return bool(row and cell and row.group(1) == cell.group(1)
                and row.group(2) == cell.group(2)
                and row.group(3) == cell.group(4))


def _clean(value: object) -> str:
    text = str(value)
    for key_name in ("GEMINI_API_KEY", "OLLAMA_API_KEY", "OPENAI_API_KEY"):
        secret = os.environ.get(key_name, "")
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return text[:12000]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--provider", choices=("gemini", "ollama_cloud", "compatible"), default="gemini")
    parser.add_argument("--mode", choices=("keyword", "hybrid"), default="keyword")
    parser.add_argument("--delay", type=float, default=1.5)
    parser.add_argument("--ids", default="", help="Optional comma-separated IDs for diagnosis")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    os.environ["DOCUMENT_AGENT_RETRIEVAL_MODE"] = args.mode
    if args.provider == "gemini" and not os.environ.get("GEMINI_API_KEY"):
        parser.error("GEMINI_API_KEY missing")
    if args.provider == "ollama_cloud" and not os.environ.get("OLLAMA_API_KEY"):
        parser.error("OLLAMA_API_KEY missing")
    if args.provider == "compatible" and not os.environ.get("COMPATIBLE_API_KEY"):
        parser.error("COMPATIBLE_API_KEY missing")

    frozen = json.loads(CASES.read_text(encoding="utf-8"))
    cases = frozen["questions"]
    if args.ids:
        selected = {int(x) for x in args.ids.split(",")}
        cases = [case for case in cases if case["id"] in selected]
        if len(cases) != len(selected):
            parser.error("Unknown case ID")
    ground_truth_hash = hashlib.sha256(CASES.read_bytes()).hexdigest()
    corpus = args.output / "fictional_corpus"
    subprocess.run([sys.executable, str(ROOT / "scripts" / "create_release_corpus.py"),
                    "--output", str(corpus)], check=True, cwd=ROOT)
    hashes = {
        name: {
            "actual": hashlib.sha256((corpus / name).read_bytes()).hexdigest(),
            "frozen": expected,
            "byte_identical": hashlib.sha256((corpus / name).read_bytes()).hexdigest()
                              == expected
        }
        for name, expected in frozen["documents_sha256"].items()
    }
    conn = connect(args.output / "evaluation.db")
    try:
        ingest_folder(conn, str(corpus))
        files = [dict(row) for row in conn.execute(
            "SELECT path,kind,status,error FROM documents ORDER BY path")]
        if sum(item["status"] == "ready" for item in files) != 8:
            raise RuntimeError("Frozen corpus indexing did not yield eight ready files")
        report = {
            "created_utc": datetime.now(UTC).isoformat(),
            "provider": args.provider,
            "model": os.environ.get({
                "gemini": "GEMINI_MODEL", "ollama_cloud": "OLLAMA_MODEL",
                "compatible": "COMPATIBLE_MODEL",
            }[args.provider], "gemini-2.5-flash"),
            "retrieval_mode_requested": args.mode,
            "ground_truth_sha256": ground_truth_hash,
            "ground_truth_label_file_unmodified": True,
            "corpus_byte_identical": all(item["byte_identical"] for item in hashes.values()),
            "corpus_note": "Regenerated fictional documents; compare hashes to frozen corpus. Some Office metadata can alter bytes without changing indexed document content.",
            "document_hashes": hashes,
            "ingestion": {"ready": 8, "failed": 1, "files": files},
            "case_count": len(cases),
            "cases": [],
            "important": ("Citations are checked for existence, but valid citations "
                          "do not prove claim correctness. Semantic correctness needs "
                          "independent reading against the frozen expected answers."),
        }
        output = args.output / "acceptance_results.json"

        def save() -> None:
            rows = report["cases"]
            report["summary"] = {
                "attempted": len(rows),
                "provider_errors": sum("provider_error" in x for x in rows),
                "verified_source_citations": sum(x.get("all_sources_resolve", False)
                                                 for x in rows),
                "expected_sources_covered": sum(x.get("all_expected_sources_covered", False)
                                                for x in rows),
                "critical_attempted": sum(x["critical"] for x in rows),
                "critical_source_covered": sum(
                    x["critical"] and x.get("all_expected_sources_covered", False)
                    for x in rows),
                "unverified": sum(x.get("verification_status") == "unverified"
                                  for x in rows),
                "actual_model_tool_cases": sum(x.get("model_tool_calls", 0) > 0
                                               for x in rows),
                "semantic_correctness": "manual review required",
            }
            output.write_text(json.dumps(report, indent=2, ensure_ascii=False),
                              encoding="utf-8")

        rate_limited_in_a_row = 0
        for i, case in enumerate(cases, 1):
            started = time.monotonic()
            entry = {
                "id": case["id"], "critical": case["critical"],
                "category": case["category"], "question": case["question"],
                "expected_answer": case["expected_answer"],
                "expected_citations": case["expected_citations"],
            }
            try:
                answer = ask(conn, case["question"], provider=args.provider)
                actual = list(dict.fromkeys(answer.sources))
                entry.update({
                    "actual_answer": _clean(answer.text),
                    "actual_citations": actual,
                    "verification_status": answer.verification_status,
                    "model_tool_calls": sum(
                        call.get("name") in {
                            "list_documents", "inspect_document", "search_documents",
                            "query_spreadsheet", "extract_dates", "get_evidence"
                        } and call.get("origin") != "application"
                        for call in answer.tool_calls),
                    "tool_audit": [{
                        "name": call.get("name"), "origin": call.get("origin", "provider"),
                        "ok": call.get("ok"),
                        "retrieval_mode": call.get("retrieval_mode"),
                        "retrieval_warning": call.get("retrieval_warning"),
                        "semantic_matches": call.get("semantic_matches")
                    } for call in answer.tool_calls],
                    "all_sources_resolve": all(
                        "error" not in get_evidence(conn, c) for c in actual),
                    "all_expected_sources_covered": all(
                        any(_citation_matches(gold, source) for source in actual)
                        for gold in case["expected_citations"]),
                    "expected_source_hits": [
                        gold for gold in case["expected_citations"]
                        if any(_citation_matches(gold, source) for source in actual)
                    ],
                })
            except Exception as exc:  # noqa: BLE001 - preserve genuine provider failures
                entry["provider_error"] = {
                    **provider_error_diagnostic(exc),
                    "exception_type": type(exc).__name__,
                }
            entry["elapsed_seconds"] = round(time.monotonic() - started, 2)
            if entry.get("provider_error", {}).get("http_status") == 429:
                rate_limited_in_a_row += 1
            elif "provider_error" not in entry or entry["provider_error"].get("http_status") != 429:
                rate_limited_in_a_row = 0
            report["cases"].append(entry)
            save()
            print(
                f"CASE {case['id']:02d}/{len(frozen['questions'])} "
                f"critical={int(case['critical'])} "
                f"status={entry.get('verification_status', 'provider_error')} "
                f"citations={len(entry.get('actual_citations', []))} "
                f"elapsed_s={entry['elapsed_seconds']}",
                flush=True,
            )
            if rate_limited_in_a_row >= 2:
                report["stopped_early"] = "Provider HTTP 429 quota reached twice consecutively; further requests suppressed."
                save()
                print("Provider quota exhausted: stopping safely after two consecutive 429s.", flush=True)
                break
            if i < len(cases):
                time.sleep(max(0.0, args.delay))
        save()
        print("FINAL SUMMARY " + json.dumps(report["summary"]), flush=True)
        # Transport or indexing errors are failures. Subjective scoring is separate.
        return 1 if report["summary"]["provider_errors"] or len(report["cases"]) != len(cases) else 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
