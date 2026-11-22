"""Measure genuine local MiniLM retrieval on the frozen corpus and live Gemini hybrid use."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from document_agent.agent import ask, provider_error_diagnostic
from document_agent.db import connect
from document_agent.hybrid import embedding_model, sync_embeddings
from document_agent.ingest import ingest_folder
from evaluate_retrieval import evaluate

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "evaluation" / "release_candidate_ground_truth.json"


def main() -> int:
    output_dir = ROOT / ".local" / "hybrid_validation"
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "hybrid_evidence.json"
    report = {"created_utc": datetime.now(UTC).isoformat(),
              "embedding": "real sentence-transformers/all-MiniLM-L6-v2",
              "requested_mode": "hybrid",
              "live_gemini": [], "passed": False}
    try:
        if not os.getenv("GEMINI_API_KEY"):
            raise RuntimeError("Gemini Actions secret not set")
        os.environ["DOCUMENT_AGENT_RETRIEVAL_MODE"] = "hybrid"
        with tempfile.TemporaryDirectory(prefix="real_hybrid_") as temp:
            corpus = Path(temp) / "corpus"
            subprocess.run([sys.executable, str(ROOT / "scripts" / "create_release_corpus.py"),
                            "--output", str(corpus)], check=True)
            conn = connect(Path(temp) / "hybrid.db")
            try:
                ingest_folder(conn, str(corpus))
                ready = conn.execute(
                    "SELECT COUNT(*) FROM documents WHERE status='ready'").fetchone()[0]
                if ready != 8:
                    raise RuntimeError("Unexpected count of readable documents")
                # A local model is actually loaded, not mocked. On CI its weights
                # may be downloaded from the upstream project.
                encoder = embedding_model()
                report["embedding_cache"] = sync_embeddings(conn, encoder=encoder)
                gold = json.loads(GOLD.read_text(encoding="utf-8"))["questions"]
                cases = [{"query": c["question"], "expected_citations": c["expected_citations"]}
                         for c in gold if c["expected_citations"]]
                report["candidate_count"] = len(cases)
                report["keyword"] = evaluate(conn, cases, mode="keyword", k=5)
                report["hybrid"] = evaluate(conn, cases, mode="hybrid", k=5)
                report["hybrid_valid"] = report["hybrid"]["valid_for_mode"]
                for case_id in (2, 11, 15):
                    case = next(c for c in gold if c["id"] == case_id)
                    item = {"id": case_id, "question": case["question"]}
                    try:
                        a = ask(conn, case["question"], provider="gemini")
                        item.update({
                            "answer": a.text[:3500],
                            "citations": a.sources,
                            "status": a.verification_status,
                            "retrieval_events": [{
                                "mode": t.get("retrieval_mode"),
                                "fallback": t.get("retrieval_warning"),
                                "semantic_matches": t.get("semantic_matches")
                            } for t in a.tool_calls if t.get("name") == "search_documents"
                                 and t.get("ok", False)],
                            "model_tool_calls": sum(
                                t.get("name") in {
                                    "search_documents", "inspect_document",
                                    "get_evidence", "extract_dates", "list_documents",
                                    "query_spreadsheet"
                                } and t.get("origin") != "application"
                                for t in a.tool_calls),
                        })
                    except Exception as exc:  # noqa: BLE001
                        item["provider_error"] = provider_error_diagnostic(exc)
                    report["live_gemini"].append(item)
                used_hybrid = any(
                    event["mode"] == "hybrid" and not event["fallback"]
                    for item in report["live_gemini"]
                    for event in item.get("retrieval_events", [])
                )
                report["actual_hybrid_model_search"] = used_hybrid
                report["passed"] = bool(
                    report["hybrid_valid"]
                    and report["hybrid"]["hit_rate_at_k"] >= 0.90
                    and used_hybrid
                    and all(not x.get("provider_error") for x in report["live_gemini"])
                )
            finally:
                conn.close()
    except Exception as exc:  # noqa: BLE001
        report["error_type"] = type(exc).__name__
        report["error"] = str(exc)[:300].replace(os.getenv("GEMINI_API_KEY", "") or
                                                  "<<<never-matches>>>", "[REDACTED]")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    print("HYBRID SUMMARY " + json.dumps({
        "passed": report["passed"],
        "keyword_hit5": report.get("keyword", {}).get("hit_rate_at_k"),
        "hybrid_hit5": report.get("hybrid", {}).get("hit_rate_at_k"),
        "fallbacks": report.get("hybrid", {}).get("fallback_cases"),
        "actual_hybrid_model_search": report.get("actual_hybrid_model_search"),
        "error_type": report.get("error_type"),
    }))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
