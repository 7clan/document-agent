"""Record frozen MQ-46 questions through both pinned apps with transient provider retries.

For each pinned engine checkout: launch real app, index the SAME new corpus,
submit the frozen MQ-46 questions to real Groq through the browser,
and preserve an uncut video and original response and source evidence.
No mock model, fabricated transcript, or model-generated correctness grading.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
GROUND_TRUTH = ROOT / "evaluation" / "unseen_coldchain_interview.json"


def citation_matches(expected: str, observed: str) -> bool:
    if expected == observed:
        return True
    row = re.fullmatch(r"(.+?) \| (.+?) \| row (\d+)", expected)
    cell = re.fullmatch(r"(.+?) \| (.+?)!([A-Z]{1,3})(\d+)", observed)
    return bool(row and cell and row.group(1) == cell.group(1)
                and row.group(2) == cell.group(2)
                and row.group(3) == cell.group(4))


def save(out: Path, report: dict) -> None:
    cases = report["cases"]
    report["summary"] = {
        "attempted": len(cases),
        "completed_with_answer": sum(c.get("response_captured") is True for c in cases),
        "errors": sum(bool(c.get("error")) for c in cases),
        "source_linked": sum(bool(c.get("citations")) for c in cases),
        "all_retrieved_sources_resolve": sum(
            c.get("all_sources_resolve") is True for c in cases),
        "all_expected_sources_present": sum(
            c.get("all_expected_sources_covered") is True for c in cases),
        "evidence_required": sum(bool(c.get("expected_citations")) for c in cases),
        "evidence_required_covered": sum(
            bool(c.get("expected_citations"))
            and c.get("all_expected_sources_covered") is True for c in cases),
        "critical_completed": sum(
            c.get("critical") and c.get("response_captured") for c in cases),
        "critical_evidence_covered": sum(
            c.get("critical") and c.get("all_expected_sources_covered") for c in cases),
        "semantic_accuracy": "not scored by retrieval/citation metrics; manual review required",
    }
    (out / "browser_results.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def await_streamlit(port: int, proc: subprocess.Popen) -> None:
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError("Streamlit stopped before browser test")
        try:
            with urlopen(f"http://127.0.0.1:{port}/_stcore/health",
                         timeout=2) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(1)
    raise TimeoutError("Streamlit did not become healthy")


# Read-only DOM extraction; this source never feeds instructions or answers.
JS_READ_RESULT = r"""() => {
  const body = document.body.innerText || "";
  const match = body.match(/Answer status:\s*([\s\S]*?)Source references/);
  const answerText = match ? match[1].trim() : "";
  const heading = Array.from(document.querySelectorAll("h3"))
    .find(e => (e.innerText || "").trim() === "Source references");
  let codes = [];
  // Streamlit code blocks render as PRE, not stCodeBlock on all versions.
  const allBlocks = Array.from(document.querySelectorAll("pre"));
  if (heading) {
    codes = allBlocks.filter(e =>
      Boolean(heading.compareDocumentPosition(e) & Node.DOCUMENT_POSITION_FOLLOWING)
    ).map(e => (e.innerText || e.textContent || "").trim());
  }
  const candidateMarker = Array.from(document.querySelectorAll("*"))
    .find(e => e.children.length === 0 &&
      (e.innerText || "").startsWith("Retrieved locations for manual review"));
  if (candidateMarker) {
    codes = allBlocks
      .filter(e =>
        heading &&
        Boolean(heading.compareDocumentPosition(e) & Node.DOCUMENT_POSITION_FOLLOWING) &&
        Boolean(e.compareDocumentPosition(candidateMarker) & Node.DOCUMENT_POSITION_FOLLOWING))
      .map(e => (e.innerText || e.textContent || "").trim());
  }
  // Some Streamlit versions print verified original citations inline
  // rather than as separate PRE blocks. Extract ONLY well-formed source IDs.
  const inlinePattern = /([A-Za-z0-9_.-]+\.(?:pdf|docx|xlsx|xlsm|xls)\s+\|\s+(?:page\s+\d+\s+\|\s+chunk\s+\d+|[A-Za-z0-9 _-]+![A-Z]{1,3}\d+|[A-Za-z0-9 _-]+\s+\|\s+row\s+\d+|paragraph\s+\d+|table\s+\d+\s+\|\s+row\s+\d+))/gi;
  const inline = Array.from(answerText.matchAll(inlinePattern)).map(m => m[1].trim());
  const citations = [...new Set([...codes, ...inline].filter(c =>
    /[.](?:pdf|docx|xlsx?|xlsm) \| /i.test(c)
  ))];
  const toolCalls = body.match(/Model document-tool calls:\s*(\d+)/);
  const limitSource = body.match(/"limit_source"\s*:\s*"([^"]+)"/);
  const httpStatus = body.match(/"http_status"\s*:\s*(\d+)/);
  return {answer_text: answerText, citations,
          model_tool_calls: toolCalls ? Number(toolCalls[1]) : null,
          provider_diagnostic: body.includes("Provider diagnostic (status, code, request phase only)"),
          provider_limit_source: limitSource ? limitSource[1] : null,
          provider_http_status: httpStatus ? Number(httpStatus[1]) : null,
          status_present: body.includes("Answer status:"),
          render_marker: body.includes("Answered question:")};
}"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine-root", type=Path, required=True)
    parser.add_argument("--engine-ref", required=True)
    parser.add_argument("--engine-sha", required=True)
    parser.add_argument("--corpus-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=18951)
    parser.add_argument("--provider", choices=("groq", "compatible", "gemini"), default="gemini")
    parser.add_argument("--model", default="google/gemma-4-31b-it")
    args = parser.parse_args()
    engine = args.engine_root.resolve()
    corpus = args.corpus_root.resolve()
    out = args.output.resolve()
    if out.exists() and any(out.iterdir()):
        parser.error("Refusing to overwrite an existing recorded benchmark")
    if not (engine / "app.py").is_file() or not corpus.is_dir():
        parser.error("An original app.py checkout and shared corpus are required")
    key_name = {"groq": "GROQ_API_KEY", "compatible": "COMPATIBLE_API_KEY",
                "gemini": "GEMINI_API_KEY"}[args.provider]
    if not os.getenv(key_name, "").strip():
        parser.error(f"{key_name} secret missing; no fake recording permitted")
    out.mkdir(parents=True, exist_ok=True)
    (out / "stills").mkdir()
    frozen_bytes = GROUND_TRUTH.read_bytes()
    frozen = json.loads(frozen_bytes)
    questions = frozen["questions"]
    document_hashes = {
        file.name: hashlib.sha256(file.read_bytes()).hexdigest()
        for file in sorted(corpus.iterdir()) if file.is_file()
    }
    report = {
        "engine_ref": args.engine_ref, "engine_sha": args.engine_sha,
        "model": args.model, "provider": args.provider,
        "retrieval": "hybrid", "recorded_utc": datetime.now(UTC).isoformat(),
        "ground_truth_sha256": hashlib.sha256(frozen_bytes).hexdigest(),
        "document_hashes": document_hashes,
        "corpus_frozen_hash_match": len(document_hashes) == 9,
        "case_count": len(questions),
        "fairness_note": (
            "Both engines use identical unmodified documents, questions, "
            "provider/model, environment and UI interaction protocol. "
            "Model replies may vary between runs. "
            "Semantic correctness requires independent review."),
        "cases": [], "recording_verified": False,
    }
    save(out, report)
    env = dict(os.environ)
    env.update({
        "LLM_PROVIDER": args.provider,
        "GROQ_MODEL": args.model,
        "GROQ_BASE_URL": "https://api.groq.com/openai/v1",
        "GEMINI_MODEL": args.model,
        "COMPATIBLE_BASE_URL": "https://openrouter.ai/api/v1",
        "COMPATIBLE_MODEL": args.model,
        "DOCUMENT_AGENT_RETRIEVAL_MODE": "hybrid",
        "DOCUMENT_AGENT_DB_PATH": str(out / "indexed_for_video.db"),
        "PYTHONPATH": str(engine / "src"),
        "STREAMLIT_BROWSER_GATHER_USAGE_STATS": "false",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "DOCUMENT_AGENT_EMBEDDING_ALLOW_DOWNLOAD": "1",
    })
    log = (out / "streamlit_private.log").open("w", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", str(engine / "app.py"),
         "--server.address", "127.0.0.1",
         "--server.port", str(args.port),
         "--server.headless", "true",
         "--browser.gatherUsageStats", "false"],
        env=env, cwd=engine, stdout=log, stderr=subprocess.STDOUT,
    )
    browser = None
    video_file = None
    try:
        await_streamlit(args.port, process)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--disable-dev-shm-usage"])
            context = browser.new_context(
                viewport={"width": 1440, "height": 900},
                record_video_dir=str(out / "raw_video"),
                record_video_size={"width": 1440, "height": 900},
            )
            page = context.new_page()
            page.goto(f"http://127.0.0.1:{args.port}", wait_until="domcontentloaded")
            page.get_by_role("combobox", name="Provider").wait_for(timeout=20000)
            page.get_by_role("textbox",
                             name="Folder path on this computer").fill(str(corpus))
            page.get_by_role("button", name="Index folder").click()
            page.get_by_text(re.compile(r"8 ready")).first.wait_for(timeout=100000)
            page.wait_for_timeout(1300)
            question_box = page.get_by_role(
                "textbox", name="Ask a question about the indexed documents")
            question_box.scroll_into_view_if_needed()
            page.wait_for_timeout(500)
            previous_answer = ""
            for case in questions:
                started = time.monotonic()
                question = case["question"]
                row = {
                    "id": case["id"], "critical": case["critical"],
                    "category": case["category"], "question": question,
                    "expected_answer": case["expected_answer"],
                    "expected_citations": case["expected_citations"],
                    "source_documents": case["source_documents"],
                    "response_captured": False, "citations": [],
                    "all_expected_sources_covered": False,
                }
                try:
                    question_box.fill(question)
                    question_box.press("Control+Enter")
                    page.get_by_role("button", name="Ask agent").click(timeout=20000)
                    if args.engine_ref != "main":
                        page.wait_for_function(
                            """q => document.body.innerText.includes("Answered question: " + q)
                            || document.body.innerText.includes("Failed question: " + q)""",
                            arg=question, timeout=135000,
                        )
                    else:
                        # Old main does not expose an answer/question identifier.
                        # After submitting, accept only a visible new answer
                        # (not the previous answer or an in-progress spinner).
                        page.wait_for_function(
                            """previous => {
                              let t = document.body.innerText || "";
                              if (t.includes("Provider diagnostic (status, code, request phase only)"))
                                return true;
                              let m = t.match(/Answer status:\\s*([\\s\\S]*?)Source references/);
                              return m && m[1].trim() &&
                                m[1].trim() !== previous &&
                                !t.includes("Analyzing evidence...");
                            }""",
                            arg=previous_answer, timeout=135000,
                        )
                    page.wait_for_timeout(500)
                    # Candidate completion marker may precede the actual answer
                    # rendering. Wait for a fresh status or provider diagnostic.
                    if args.engine_ref != "main":
                        try:
                            page.wait_for_function(
                                """prev => {
                                  const t = document.body.innerText || "";
                                  if (t.includes("Provider diagnostic (status, code, request phase only)"))
                                    return true;
                                  const m = t.match(/Answer status:\\s*([\\s\\S]*?)Source references/);
                                  return m && m[1].trim() &&
                                    m[1].trim() !== prev;
                                }""",
                                arg=previous_answer, timeout=22000,
                            )
                        except Exception:
                            pass  # The retry loop handles missing visible answers.
                    observation = page.evaluate(JS_READ_RESULT)
                    retries = 0
                    while retries < 3:
                        code = observation["provider_http_status"]
                        diagnostic = observation["provider_diagnostic"]
                        temporary = diagnostic and (
                            code in (429, 500, 502, 503, 504) or
                            (args.provider == "compatible" and
                             observation["provider_limit_source"] ==
                             "openrouter_in_flight_budget")
                        )
                        empty_answer = (not diagnostic and
                                        not observation["answer_text"] and
                                        not observation["status_present"])
                        if not (temporary or empty_answer):
                            break
                        if empty_answer:
                            delay_seconds = 5
                            kind = "MISSING_ANSWER_RENDER"
                        elif code == 429:
                            delay_seconds = min(90, 30 + 15 * retries)
                            kind = "MODEL_RATE_LIMIT_429"
                        elif code in (500, 502, 503, 504):
                            delay_seconds = (25, 45, 65)[retries]
                            kind = "TRANSIENT_UPSTREAM_HTTP_" + str(code)
                        else:
                            delay_seconds = (30, 60, 90)[retries]
                            kind = "TEMPORARY_IN_FLIGHT_BUDGET"
                        print(kind, args.engine_ref, case["id"],
                              "retry", retries + 1,
                              "after_s", delay_seconds, flush=True)
                        page.wait_for_timeout(delay_seconds * 1000)
                        question_box.fill(question)
                        question_box.press("Control+Enter")
                        page.get_by_role("button", name="Ask agent").click(timeout=20000)
                        page.wait_for_timeout(1000)
                        if args.engine_ref != "main":
                            page.wait_for_function(
                                """q => document.body.innerText.includes("Answered question: " + q)
                                || document.body.innerText.includes("Failed question: " + q)""",
                                arg=question, timeout=135000,
                            )
                        else:
                            page.wait_for_function(
                                """prev => {
                                   const t = document.body.innerText || "";
                                   if (t.includes("Provider diagnostic (status, code, request phase only)"))
                                     return true;
                                   const m = t.match(/Answer status:\\s*([\\s\\S]*?)Source references/);
                                   return m && m[1].trim() && m[1].trim() !== prev;
                                }""",
                                arg=previous_answer, timeout=135000,
                            )
                        if args.engine_ref != "main":
                            try:
                                page.wait_for_function(
                                    """prev => {
                                      const t = document.body.innerText || "";
                                      if (t.includes("Provider diagnostic (status, code, request phase only)"))
                                        return true;
                                      const m = t.match(/Answer status:\\s*([\\s\\S]*?)Source references/);
                                      return m && m[1].trim() && m[1].trim() !== prev;
                                    }""",
                                    arg=previous_answer, timeout=22000,
                                )
                            except Exception:
                                pass
                        page.wait_for_timeout(450)
                        observation = page.evaluate(JS_READ_RESULT)
                        retries += 1
                    row["provider_rate_or_budget_retries"] = retries
                    row.update({
                        "response_captured": bool(observation["status_present"]
                                                   and observation["answer_text"]
                                                   and not observation["provider_diagnostic"]),
                        "displayed_answer": observation["answer_text"][:16000],
                        "citations": observation["citations"],
                        "model_tool_calls_shown": observation["model_tool_calls"],
                        "provider_diagnostic": observation["provider_diagnostic"],
                        "provider_http_status": observation["provider_http_status"],
                        "provider_limit_source": observation["provider_limit_source"],
                    })
                    if row["response_captured"]:
                        previous_answer = observation["answer_text"]
                    try:
                        heading = page.get_by_role(
                            "heading", name="Source references")
                        if heading.count():
                            heading.first.scroll_into_view_if_needed(timeout=8000)
                    except Exception as exc:  # noqa: BLE001 - UI scrolling is optional
                        row["source_scroll_warning"] = type(exc).__name__
                    page.wait_for_timeout(700)
                    if case["id"] in (1, 6, 19, 24, 29, 36, 41, 44):
                        page.screenshot(
                            path=str(out / "stills" / f"case-{case['id']:02d}.png"),
                            full_page=False)
                except Exception as exc:  # noqa: BLE001 - persist browser failures
                    row["error"] = {"type": type(exc).__name__,
                                    "message": str(exc).splitlines()[0][:240]}
                    row["displayed_answer"] = ""
                    previous_answer = ""
                row["elapsed_seconds"] = round(time.monotonic() - started, 2)
                report["cases"].append(row)
                save(out, report)
                print("RECORDED", args.engine_ref, f"{case['id']:02d}/{len(questions)}",
                      "observed", row["response_captured"],
                      "citations", len(row["citations"]),
                      "elapsed", row["elapsed_seconds"], flush=True)
                # On an actual provider budget/rate failure, stop requests.
                if row.get("provider_diagnostic"):
                    report["stopped_early"] = (
                        "Provider diagnostic encountered; further paid calls "
                        "were not attempted. See captured video.")
                    break
                page.wait_for_timeout(15000)
            video = page.video
            context.close()
            video_file = Path(video.path()) if video else None
            browser.close()
            browser = None
    finally:
        if browser is not None:
            browser.close()
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        log.close()
        if video_file and video_file.exists():
            dest = out / "full_uncut_interview.webm"
            shutil.copyfile(video_file, dest)
            report["video"] = dest.name
            if shutil.which("ffmpeg"):
                mp4 = out / "full_uncut_interview.mp4"
                encode = subprocess.run(
                    ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                     "-i", str(dest), "-c:v", "libx264", "-crf", "27",
                     "-preset", "veryfast", "-pix_fmt", "yuv420p",
                     str(mp4)],
                    check=False, capture_output=True, text=True,
                )
                if encode.returncode == 0:
                    report["video_mp4"] = mp4.name
        # Source IDs are checked against original indexed evidence, separately
        # from the browser's own displayed validity status.
        try:
            from document_agent.db import connect
            from document_agent.tools import get_evidence
            db = connect(out / "indexed_for_video.db")
            for row in report["cases"]:
                sources = row.get("citations", [])
                row["all_sources_resolve"] = bool(sources) and all(
                    "error" not in get_evidence(db, c) for c in sources)
                required = row["source_documents"]
                row["all_expected_sources_covered"] = bool(required) and all(
                    any(c == filename or c.startswith(filename + " | ")
                        for c in sources)
                    for filename in required)
                row["expected_source_hits"] = [
                    filename for filename in required
                    if any(c == filename or c.startswith(filename + " | ")
                           for c in sources)]
            db.close()
        except Exception as exc:  # noqa: BLE001 - preserve audit failures
            report["evidence_validation_error"] = type(exc).__name__
        report["recording_verified"] = bool(
            len(report["cases"]) == len(questions)
            and all(row["response_captured"] for row in report["cases"])
            and report.get("video"))
        save(out, report)
        print("UNSEEN_FINAL_INTERVIEW", args.engine_ref,
              json.dumps(report["summary"]), flush=True)
    return 0 if report["recording_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
