"""Record the real Streamlit app and genuine provider answers in Chromium.

No mocking, canned replies, or screenshots substituted for model calls.
Requires a working GEMINI_API_KEY, supplied privately in .env or the environment.
Outputs and source documents stay under .local/ (Git-ignored).
"""
from __future__ import annotations

import argparse
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

from dotenv import load_dotenv

QUESTIONS = [
    ("semantic", "Which electrical cabinets must be brought into service?", True),
    ("exact_below", "Does HP-103 exceed SAR 1 million?", False),
    ("exact_above", "Does HP-1030 exceed SAR 1 million?", False),
    ("missing_id", "What amount belongs to exact item HP-999?", False),
    ("damaged", "Can the damaged attachment establish any new approval?", False),
    ("approval", "Is the 5 December 2028 handover proposal approved and binding?", True),
]


def _wait_for_server(port: int, process: subprocess.Popen, timeout: int = 90) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Streamlit server stopped before browser launch")
        try:
            with urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=2) as reply:
                if reply.status == 200:
                    return
        except OSError:
            time.sleep(1)
    raise RuntimeError("Timed out starting Streamlit")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18951)
    parser.add_argument("--output", default="", help="Unique empty output folder")
    args = parser.parse_args()
    load_dotenv()
    if not os.getenv("GEMINI_API_KEY", "").strip():
        print("LIVE RECORDING BLOCKED: GEMINI_API_KEY unavailable. "
              "No model video has been generated.", file=sys.stderr)
        return 2

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Install Playwright first: pip install playwright && "
              "python -m playwright install chromium", file=sys.stderr)
        return 2

    root = Path.cwd()
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = (Path(args.output) if args.output else
           root / ".local" / "release_browser_recordings" / timestamp).resolve()
    if out.exists() and any(out.iterdir()):
        parser.error(f"Refusing to overwrite prior recording: {out}")
    out.mkdir(parents=True, exist_ok=True)
    corpus = out / "fictional_documents"
    subprocess.run([sys.executable, "scripts/create_release_corpus.py",
                    "--output", str(corpus)], check=True, cwd=root)
    db_path = out / "live_recording.db"
    env = dict(os.environ, LLM_PROVIDER="gemini",
               DOCUMENT_AGENT_DB_PATH=str(db_path),
               DOCUMENT_AGENT_RETRIEVAL_MODE="keyword")
    server_log = (out / "streamlit_server.log").open("w", encoding="utf-8")
    server = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "app.py",
         "--server.port", str(args.port), "--server.address", "127.0.0.1",
         "--server.headless", "true", "--browser.gatherUsageStats", "false"],
        cwd=root, env=env, stdout=server_log, stderr=subprocess.STDOUT,
    )
    report = {"provider": "gemini", "model": os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
              "live_provider_cases": 0, "successful_provider_cases": 0,
              "questions": [], "recording_verified": False}
    video_path = None
    try:
        _wait_for_server(args.port, server)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1600, "height": 900},
                                          record_video_dir=str(out / "raw_video"),
                                          record_video_size={"width": 1600, "height": 900})
            page = context.new_page()
            page.goto(f"http://127.0.0.1:{args.port}", wait_until="domcontentloaded")
            page.get_by_role("textbox", name="Folder path on this computer").fill(str(corpus))
            page.get_by_role("button", name="Index folder").click()
            page.get_by_text(re.compile(r"8 ready")).first.wait_for(timeout=90000)
            question_box = page.get_by_role(
                "textbox", name="Ask a question about the indexed documents"
            )
            for category, question, needs_model in QUESTIONS:
                question_box.fill(question)
                # Streamlit text_area keeps edits pending until Ctrl+Enter or blur.
                # A click on a disabled Ask button does not commit pending edits.
                question_box.press("Control+Enter")
                ask_button = page.get_by_role("button", name="Ask agent")
                from playwright.sync_api import expect

                expect(ask_button).to_be_enabled(timeout=15000)
                ask_button.click()
                try:
                    page.get_by_text(re.compile(r"Answer status:")).first.wait_for(
                        state="visible", timeout=130000
                    )
                    page.wait_for_timeout(600)
                    body = page.locator("body").inner_text()
                    excerpt = body.rsplit("Answer status:", 1)[-1].split(
                        "Source references", 1
                    )[0].strip()[:3000]
                    tool_match = re.search(r"Model document-tool calls:\s*(\d+)", body)
                    model_calls = int(tool_match.group(1)) if tool_match else 0
                    source_links = page.get_by_role("button", name="Open source").count()
                    provider_ok = bool(excerpt and
                                       "provider diagnostic" not in excerpt.casefold())
                    if needs_model:
                        report["live_provider_cases"] += 1
                        provider_ok = provider_ok and model_calls > 0 and source_links > 0
                        if provider_ok:
                            report["successful_provider_cases"] += 1
                    report["questions"].append({
                        "category": category, "question": question,
                        "needs_live_provider": needs_model,
                        "completed": provider_ok,
                        "model_tool_calls": model_calls,
                        "source_open_controls": source_links,
                        "observed_answer": excerpt,
                    })
                except Exception as exc:  # noqa: BLE001 - preserve truthful failure log
                    report["questions"].append({
                        "category": category, "question": question,
                        "needs_live_provider": needs_model,
                        "completed": False, "error_type": type(exc).__name__,
                    })
                page.wait_for_timeout(750)
            video = page.video
            context.close()
            video_path = Path(video.path()) if video is not None else None
            browser.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait()
        server_log.close()
        if video_path and video_path.exists():
            dest = out / "uncut_browser_recording.webm"
            shutil.copyfile(video_path, dest)
            report["video"] = str(dest)
            if shutil.which("ffmpeg"):
                mp4 = out / "uncut_browser_recording.mp4"
                subprocess.run([
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-i", str(dest), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    str(mp4),
                ], check=True)
                report["video_mp4"] = str(mp4)
        report["recording_verified"] = bool(
            report["successful_provider_cases"] >= 2
            and len(report["questions"]) == len(QUESTIONS)
            and all(item["completed"] for item in report["questions"])
            and report.get("video")
        )
        (out / "recording_results.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        print("Recording report: " + str(out / "recording_results.json"))
        print("Genuine provider responses: " +
              str(report["successful_provider_cases"]) + "/" +
              str(report["live_provider_cases"]))
        if not report["recording_verified"]:
            print("Recording is NOT a validated live-model demonstration.")
    return 0 if report["recording_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
