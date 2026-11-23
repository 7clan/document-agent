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

from document_agent.agent import _retry_after_seconds, ask, provider_error_diagnostic
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


def summarize_cases(rows: list[dict]) -> dict:
    """Separate cited answers, cautious abstentions and provider failures.

    Never count an empty citation list as proof of source resolution. An answer
    with all labeled sources is not necessarily semantically correct.
    """
    cited = [row for row in rows if row.get("actual_citations")]
    return {
        "attempted": len(rows),
        "provider_errors": sum("provider_error" in row for row in rows),
        "provider_http_402": sum(
            row.get("provider_error", {}).get("http_status") == 402 for row in rows),
        "provider_http_429": sum(
            row.get("provider_error", {}).get("http_status") == 429 for row in rows),
        "answers_with_citations": len(cited),
        "answers_without_citations": sum(
            "provider_error" not in row and not row.get("actual_citations")
            for row in rows),
        "verified_source_citations": sum(
            row.get("all_sources_resolve") is True for row in cited),
        "expected_sources_covered": sum(
            row.get("all_expected_sources_covered") is True for row in rows),
        # The legacy field above includes intentionally citation-free cases.
        # The following measures only questions that actually require citations.
        "evidence_required_cases": sum(
            bool(row.get("expected_citations")) for row in rows),
        "evidence_required_all_expected_sources": sum(
            bool(row.get("expected_citations")) and
            row.get("all_expected_sources_covered") is True for row in rows),
        "critical_evidence_required_cases": sum(
            bool(row.get("critical")) and bool(row.get("expected_citations"))
            for row in rows),
        "critical_evidence_required_all_expected_sources": sum(
            bool(row.get("critical")) and bool(row.get("expected_citations"))
            and row.get("all_expected_sources_covered") is True for row in rows),
        "citation_free_expected_cases": sum(
            not row.get("expected_citations") for row in rows),
        "critical_attempted": sum(bool(row.get("critical")) for row in rows),
        "critical_source_covered": sum(
            bool(row.get("critical")) and
            row.get("all_expected_sources_covered") is True for row in rows),
        "unverified": sum(row.get("verification_status") == "unverified"
                          for row in rows),
        "actual_model_tool_cases": sum(row.get("model_tool_calls", 0) > 0
                                       for row in rows),
        "semantic_correctness": "manual review required",
    }


def resume_cases(report: dict, previous: dict, cases: list[dict]) -> int:
    """Resume only completed, unchanged questions from a matching provider run.

    A final 402/429 error is retried, never silently counted as completed.
    Refuse any change to the frozen question labels, model or retrieval mode.
    """
    for field in ("provider", "model", "ground_truth_sha256",
                  "retrieval_mode_requested", "case_count"):
        if previous.get(field) != report.get(field):
            raise ValueError(f"Refusing incompatible checkpoint: {field}")
    saved = previous.get("cases")
    if not isinstance(saved, list) or len(saved) > len(cases):
        raise ValueError("Checkpoint cases invalid or exceed frozen question count")
    accepted = []
    for i, entry in enumerate(saved):
        case = cases[i]
        if (not isinstance(entry, dict) or entry.get("id") != case["id"]
                or entry.get("question") != case["question"]
                or entry.get("expected_answer") != case["expected_answer"]
                or entry.get("expected_citations") != case["expected_citations"]
                or entry.get("critical") != case["critical"]):
            raise ValueError(f"Checkpoint ground truth mismatch at case {case['id']}")
        error = entry.get("provider_error")
        if error:
            if (i != len(saved) - 1
                    or error.get("http_status") not in (402, 429)):
                raise ValueError("Only a trailing 402/429 interruption is resumable")
            break
        if "actual_answer" not in entry or "verification_status" not in entry:
            raise ValueError("Checkpoint contains an incomplete answer")
        accepted.append(entry)
    report["cases"] = accepted
    report["resume"] = {
        "previously_answered": len(accepted),
        "resumed_from_question": (cases[len(accepted)]["id"]
                                  if len(accepted) < len(cases) else None),
        "checkpoint_compatibility_verified": True,
    }
    return len(accepted)


def retry_temporary_budget(conn, question: str, provider: str) -> tuple[object, int]:
    """Retry only OpenRouter in-flight budget 402; not exhausted credits."""
    for attempt in range(4):
        try:
            return ask(conn, question, provider=provider), attempt
        except Exception as exc:
            safe = provider_error_diagnostic(exc)
            if (safe.get("http_status") != 402
                    or safe.get("limit_source") != "openrouter_in_flight_budget"
                    or attempt >= 3):
                raise
            suggested = _retry_after_seconds(exc)
            if suggested is None:
                suggested = (12.0, 25.0, 45.0)[attempt]
            delay = min(90.0, max(5.0, float(suggested)))
            print(f"Temporary OpenRouter in-flight budget (HTTP 402): "
                  f"retry {attempt + 1}/3 after {delay:.0f}s", flush=True)
            time.sleep(delay)
    raise AssertionError("Unreachable transient-provider retry path")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--provider", choices=("gemini", "ollama_cloud", "compatible"), default="gemini")
    parser.add_argument("--mode", choices=("keyword", "hybrid"), default="keyword")
    parser.add_argument("--delay", type=float, default=1.5)
    parser.add_argument("--corpus-root", type=Path, default=None,
                        help="Use byte-identical external shared corpus without regenerating")
    parser.add_argument("--ids", default="", help="Optional comma-separated IDs for diagnosis")
    parser.add_argument("--resume", action="store_true", help="Continue a verified JSON checkpoint")
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
    corpus = (args.corpus_root.resolve() if args.corpus_root is not None
              else args.output / "fictional_corpus")
    if args.corpus_root is None:
        subprocess.run([sys.executable, str(ROOT / "scripts" / "create_release_corpus.py"),
                        "--output", str(corpus)], check=True, cwd=ROOT)
    elif not corpus.is_dir():
        parser.error("--corpus-root must be an existing indexed-document folder")
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
            "engine_ref": os.getenv("COMPARISON_ENGINE_REF", "unspecified"),
            "engine_sha": os.getenv("COMPARISON_ENGINE_SHA", "unspecified"),
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
            report["summary"] = summarize_cases(report["cases"])
            output.write_text(json.dumps(report, indent=2, ensure_ascii=False),
                              encoding="utf-8")

        offset = 0
        if args.resume:
            if not output.is_file():
                parser.error("--resume requested but previous acceptance_results.json is missing")
            previous = json.loads(output.read_text(encoding="utf-8"))
            offset = resume_cases(report, previous, cases)
            # Verify the original indexed citations can still be resolved.
            for previous_case in report["cases"]:
                if any("error" in get_evidence(conn, citation)
                       for citation in previous_case.get("actual_citations", [])):
                    raise ValueError("A preserved citation no longer resolves in the corpus")
            print(f"RESUMED {offset} previously completed questions "
                  f"from an exact matching frozen corpus", flush=True)
            save()
        rate_limited_in_a_row = 0
        for i, case in enumerate(cases[offset:], offset + 1):
            started = time.monotonic()
            entry = {
                "id": case["id"], "critical": case["critical"],
                "category": case["category"], "question": case["question"],
                "expected_answer": case["expected_answer"],
                "expected_citations": case["expected_citations"],
            }
            try:
                answer, transient_retries = retry_temporary_budget(
                    conn, case["question"], args.provider)
                entry["temporary_budget_retries"] = transient_retries
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
                    "all_sources_resolve": bool(actual) and all(
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
            if entry.get("provider_error", {}).get("http_status") == 402:
                report["stopped_early"] = ("Provider HTTP 402 billing or access restriction; "
                                           "remaining model requests intentionally skipped.")
                save()
                print("Provider billing restriction HTTP 402: stopping safely.", flush=True)
                break
            if rate_limited_in_a_row >= 2:
                report["stopped_early"] = ("Provider HTTP 429 quota reached twice "
                                           "consecutively; further requests suppressed.")
                save()
                print("Provider quota exhausted: stopping safely after two consecutive 429s.",
                      flush=True)
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
