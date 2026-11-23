"""Live OpenRouter Gemma 4 smoke: test real OpenAI-compatible tool exchange."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from document_agent.agent import ask, provider_error_diagnostic
from document_agent.db import connect
from document_agent.ingest import ingest_folder

MODEL = "google/gemma-4-31b-it"
ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    if not os.getenv("OPENROUTER_API_KEY"):
        print("OpenRouter secret unavailable. No request was made.")
        return 2
    os.environ["COMPATIBLE_API_KEY"] = os.environ["OPENROUTER_API_KEY"]
    os.environ["COMPATIBLE_BASE_URL"] = "https://openrouter.ai/api/v1"
    os.environ["COMPATIBLE_MODEL"] = MODEL
    os.environ["LLM_PROVIDER"] = "compatible"
    output = ROOT / ".local" / "openrouter"
    output.mkdir(parents=True, exist_ok=True)
    report = {"provider": "OpenRouter", "model": MODEL, "cases": []}
    try:
        with tempfile.TemporaryDirectory(prefix="gemma_real_") as td:
            corpus = Path(td) / "fictional"
            subprocess.run([sys.executable, str(ROOT / "scripts" / "create_release_corpus.py"),
                            "--output", str(corpus)], check=True, stdout=subprocess.DEVNULL)
            conn = connect(Path(td) / "index.sqlite")
            try:
                ingest_folder(conn, str(corpus))
                for question in (
                    "Which electrical cabinets must be brought into service?",
                    "Is the 5 December 2028 handover proposal approved and binding?",
                    "Does HP-1030 exceed SAR 1 million?",
                ):
                    case = {"question": question}
                    try:
                        ans = ask(conn, question, provider="compatible", model=MODEL)
                        case.update({
                            "answer": ans.text[:2500],
                            "citations": ans.sources,
                            "status": ans.verification_status,
                            "tool_calls": sum(
                                x.get("name") in {
                                    "search_documents", "get_evidence", "inspect_document",
                                    "list_documents", "query_spreadsheet", "extract_dates"
                                } and x.get("origin") != "application"
                                for x in ans.tool_calls),
                        })
                    except Exception as exc:  # noqa: BLE001 - sanitize provider errors
                        case["provider_error"] = {
                            **provider_error_diagnostic(exc),
                            "exception_type": type(exc).__name__,
                        }
                    report["cases"].append(case)
            finally:
                conn.close()
    except Exception as exc:  # noqa: BLE001
        report["setup_error_type"] = type(exc).__name__
    model_cases = report["cases"][:2]
    report["live_success"] = (
        len(report["cases"]) == 3
        and all(not x.get("provider_error") and x.get("citations") and x.get("tool_calls", 0)
                for x in model_cases)
        and not report["cases"][2].get("provider_error")
    )
    (output / "gemma_openrouter_results.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("OPENROUTER SUMMARY " + json.dumps({
        "model": MODEL, "attempted": len(report["cases"]),
        "live_success": report["live_success"],
        "model_tool_calls": [x.get("tool_calls", 0) for x in model_cases],
        "provider_error_codes": [x.get("provider_error", {}).get("code")
                                 for x in model_cases],
    }))
    return 0 if report["live_success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
