"""Offline release-corpus coverage of host-owned safety guards.

This deliberately prohibits every model call. It measures which frozen
questions are resolvable without an external provider, not LLM accuracy.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import document_agent.agent as module
from document_agent.db import connect
from document_agent.ingest import ingest_folder
from document_agent.tools import get_evidence

ROOT = Path(__file__).resolve().parents[1]


class ModelNeeded(RuntimeError):
    """Sentinel raised instead of allowing an external model request."""


def block_provider(*_args, **_kwargs):
    raise ModelNeeded


def main() -> int:
    output = ROOT / ".local" / "host_coverage"
    output.mkdir(parents=True, exist_ok=True)
    original = module._ask_gemini
    result = {
        "tested_utc": datetime.now(UTC).isoformat(),
        "model_calls_allowed": False,
        "results": [],
    }
    try:
        with tempfile.TemporaryDirectory(prefix="host_guards_") as td:
            corpus = Path(td) / "docs"
            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "create_release_corpus.py"),
                 "--output", str(corpus)],
                check=True, cwd=ROOT, stdout=subprocess.DEVNULL)
            conn = connect(Path(td) / "documents.db")
            try:
                ingest_folder(conn, str(corpus))
                case_path = ROOT / "evaluation" / "release_candidate_ground_truth.json"
                cases = json.loads(case_path.read_text(encoding="utf-8"))["questions"]
                module._ask_gemini = block_provider
                for entry in cases:
                    row = {"id": entry["id"], "critical": entry["critical"],
                           "question": entry["question"]}
                    try:
                        a = module.ask(conn, entry["question"], provider="gemini")
                    except ModelNeeded:
                        row["routing"] = "external_model_required"
                    else:
                        row.update({
                            "routing": "application_answered",
                            "answer": a.text[:1400],
                            "citations": a.sources,
                            "status": a.verification_status,
                            "source_locations_resolve": bool(a.sources) and all(
                                "error" not in get_evidence(conn, cite)
                                for cite in a.sources),
                            "host_audit": [call["name"] for call in a.tool_calls
                                           if call.get("origin") == "application"],
                        })
                    result["results"].append(row)
            finally:
                module._ask_gemini = original
                conn.close()
    except Exception as exc:  # noqa: BLE001 - preserve offline audit failure type
        result["failure_type"] = type(exc).__name__
    result["summary"] = {
        "total": len(result["results"]),
        "host_answered": sum(row["routing"] == "application_answered"
                             for row in result["results"]),
        "requires_provider": sum(row["routing"] == "external_model_required"
                                 for row in result["results"]),
        "host_source_resolved": sum(
            row.get("source_locations_resolve") is True
            for row in result["results"]),
        "host_critical_answered": sum(
            row["critical"] and row["routing"] == "application_answered"
            for row in result["results"]),
        "real_model_requests": 0,
        "semantic_accuracy": "not evaluated",
    }
    (output / "host_coverage.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print("HOST_COVERAGE " + json.dumps(result["summary"]), flush=True)
    return 0 if result["summary"]["total"] == 44 and "failure_type" not in result else 1


if __name__ == "__main__":
    raise SystemExit(main())
