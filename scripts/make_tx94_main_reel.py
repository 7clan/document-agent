"""Combine only authentic, independently correct MAIN Q&A intervals into a reel.

No model calls. Never redraw or fabricate the application's screen. Every
cut is disclosed with original timestamps and the full video is preserved.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path


def run(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True,
                            check=False, timeout=240)
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-1700:])


def duration(path: Path) -> float:
    output = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        text=True, timeout=20,
    ).strip()
    return float(output)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--video", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--semantic-report", type=Path, required=True)
    p.add_argument("--rubric", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    recorded = json.loads(args.report.read_text(encoding="utf-8"))
    review = json.loads(args.semantic_report.read_text(encoding="utf-8"))
    key = json.loads(args.rubric.read_text(encoding="utf-8"))
    if recorded.get("engine_ref") != "main":
        raise ValueError("Reel may only show real original main")
    cases = {row["id"]: row for row in recorded["cases"]}
    verified = {row["id"] for row in review["results"]["main"]["cases"]
                if row["semantic_label"] == "correct" and row["captured"]}
    gold = {row["id"]: row for row in key["questions"]}
    chosen = [1, 3, 5, 7]
    if any(i not in verified for i in chosen):
        raise ValueError("Cannot publish reel; a selected case failed independent review")
    original_length = duration(args.video)
    snippets: list[dict] = []

    for id_ in chosen:
        c = cases[id_]
        q = gold[id_]
        if (not c.get("response_captured")
                or c.get("provider_diagnostic") or
                not c.get("all_sources_resolve") or
                not c.get("citations") or
                not c.get("displayed_answer")):
            raise ValueError(f"Question {id_} is not a proven captured answer")
        if not all(re.search(exp, c["displayed_answer"], re.IGNORECASE)
                   for exp in q["required"]):
            raise ValueError(f"Question {id_} misses a required factual anchor")
        start = max(0., float(c["video_start_seconds"]) - 0.2)
        end = min(original_length - 0.1, float(c["video_end_seconds"]) + 2.0)
        if end - start <= 2.:
            raise ValueError(f"Question {id_} has unusable video interval")
        video = args.output / f"_case_{id_:02d}.mp4"
        run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-ss", f"{start:.2f}", "-i", str(args.video),
            "-t", f"{end-start:.2f}",
            "-an", "-vf",
            "scale=-2:720,fps=18,tpad=stop_mode=clone:stop_duration=2",
            "-c:v", "libx264", "-crf", "28", "-preset", "veryfast",
            "-pix_fmt", "yuv420p", str(video),
        ])
        snippets.append({
            "question_id": id_, "question": c["question"],
            "answer_as_recorded": c["displayed_answer"],
            "citations": c["citations"], "independently_judged": "correct",
            "all_citations_resolve": c["all_sources_resolve"],
            "original_interval_seconds": [round(start, 2), round(end, 2)],
            "segment_mp4": video.name,
        })

    playlist = args.output / "_segments.txt"
    playlist.write_text(
        "".join(f"file '{s['segment_mp4']}'\n" for s in snippets),
        encoding="utf-8",
    )
    reel = args.output / "tx94_main_linkedin_reel.mp4"
    run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "concat", "-safe", "0", "-i", str(playlist),
        "-c", "copy", "-movflags", "+faststart", str(reel),
    ])
    manifest = {
        "title": "Document Intelligence Agent — real original-main TX94 unseen interview",
        "engine_commit": recorded["engine_sha"],
        "model": recorded["model"],
        "question_ids": chosen,
        "question_count": len(chosen),
        "source_video": str(args.video),
        "duration_seconds": round(duration(reel), 2),
        "editing_disclosure": (
            "Edited sequence of four real, correct, citation-resolvable "
            "first-answer interactions from one uncut real browser session. "
            "Unrelated questions and waiting periods between questions were "
            "removed. Each final answer was held for two extra seconds for "
            "readability. No answer text, numbers, references, or model output "
            "was altered. The uncut recording is retained in GitHub Actions."
        ),
        "segments": snippets,
    }
    (args.output / "tx94_main_reel_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    for file in [*args.output.glob("_case_*.mp4"), playlist]:
        file.unlink(missing_ok=True)
    print("LINKEDIN_MAIN_REEL_READY", json.dumps({
        "questions": chosen, "duration": manifest["duration_seconds"],
        "size_bytes": reel.stat().st_size,
        "original_answers_unchanged": True,
    }), flush=True)


if __name__ == "__main__":
    main()
