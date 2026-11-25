"""Create an honest short LinkedIn demo of ONE successful real main response.

The input is the original uncut Playwright recording; never re-create text or
splice in a different model's answer. Selection is deterministic and happens
after the report is saved. Publish no clip if the answer is missing, has an
unresolved citation or fails the predeclared key-fact checks.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path


def clip_candidate(rows: list[dict], questions: list[dict]) -> tuple[dict, dict] | None:
    by_id = {int(q["id"]): q for q in questions}
    priority = [1, 3, 7, 2, 4, 6, 5, 8]
    eligible: list[tuple[dict, dict]] = []
    for case in rows:
        expected = by_id.get(case.get("id"))
        if expected is None:
            continue
        text = case.get("displayed_answer", "")
        if (not case.get("response_captured") or case.get("provider_diagnostic")
                or not case.get("all_sources_resolve")
                or not case.get("citations") or not text.strip()):
            continue
        if re.search(r"(?i)provider (?:time budget|rate limit)|no grounded answer", text):
            continue
        if not all(re.search(pattern, text, re.IGNORECASE)
                   for pattern in expected["required"]):
            continue
        if (case.get("video_start_seconds") is None
                or case.get("video_end_seconds") is None):
            continue
        eligible.append((case, expected))
    eligible.sort(key=lambda x: (
        not bool(x[0].get("all_expected_sources_covered")),
        priority.index(x[0]["id"]) if x[0]["id"] in priority else 999,
    ))
    return eligible[0] if eligible else None


def execute(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True,
                            check=False, timeout=240)
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-1600:] or "ffmpeg failed")


def get_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True, timeout=15,
    )
    return float(result.stdout.strip())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--rubric", type=Path, required=True)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    gold = json.loads(args.rubric.read_text(encoding="utf-8"))
    if report.get("engine_ref") != "main":
        raise ValueError("Only original main may be used for this video")
    selection = clip_candidate(report["cases"], gold["questions"])
    args.output.mkdir(parents=True, exist_ok=True)
    if selection is None:
        print("LINKEDIN_CLIP_NOT_PUBLISHED no eligible correct cited response",
              flush=True)
        return
    case, question = selection
    duration = get_duration(args.video)
    start = max(0.0, float(case["video_start_seconds"]) - 2)
    end = min(duration - 0.1, float(case["video_end_seconds"]) + 4)
    if end - start <= 1:
        raise RuntimeError("Recorded video timestamps are invalid")
    output = args.output / "tx94_main_linkedin_highlight.mp4"
    common = ["-an", "-r", "18", "-vf", "scale=-2:720",
              "-c:v", "libx264", "-crf", "28",
              "-preset", "veryfast", "-pix_fmt", "yuv420p",
              "-movflags", "+faststart"]
    was_shortened = end - start > 75
    if was_shortened:
        # Preserve the actual question on screen and the complete answer;
        # omit only the middle of the waiting/spinner period.
        opening_end = start + 12
        closing_start = max(opening_end + 1, end - 43)
        first = args.output / "_opening.mp4"
        last = args.output / "_answer.mp4"
        execute(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                 "-ss", str(start), "-i", str(args.video), "-t",
                 str(opening_end - start), *common, str(first)])
        execute(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                 "-ss", str(closing_start), "-i", str(args.video), "-t",
                 str(end - closing_start), *common, str(last)])
        playlist = args.output / "_playlist.txt"
        playlist.write_text(
            "file '_opening.mp4'\nfile '_answer.mp4'\n", encoding="utf-8",
        )
        execute(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                 "-f", "concat", "-safe", "0", "-i", str(playlist),
                 "-c", "copy", "-movflags", "+faststart", str(output)])
        for file in (first, last, playlist):
            file.unlink(missing_ok=True)
    else:
        execute(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                 "-ss", str(start), "-i", str(args.video), "-t",
                 str(end - start), *common, str(output)])

    thumbnail = args.output / "tx94_main_answer_frame.jpg"
    execute(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-ss", str(max(0, get_duration(output) - 2)),
             "-i", str(output), "-frames:v", "1", str(thumbnail)])

    manifest = {
        "dataset": gold["dataset"],
        "engine": "original unmodified main",
        "commit": report["engine_sha"],
        "model": report["model"],
        "question_id": case["id"],
        "question": case["question"],
        "answer_as_recorded": case["displayed_answer"],
        "citation_references": case["citations"],
        "all_citations_resolve": case["all_sources_resolve"],
        "all_expected_source_documents_covered":
            case.get("all_expected_sources_covered"),
        "recording_source": str(args.video),
        "source_start_seconds": round(start, 2),
        "source_end_seconds": round(end, 2),
        "edited_out_wait_time": was_shortened,
        "editing_disclosure": (
            "Only a middle waiting-spinner segment was removed. The question "
            "and final answer are authentic and unchanged. Full uncut "
            "recording is preserved in the GitHub workflow artifact."
            if was_shortened else
            "Only the successful question interval was trimmed from the "
            "authentic uncut browser recording; the answer is unchanged."
        ),
        "mp4_duration_seconds": round(get_duration(output), 2),
        "output_mp4": output.name,
    }
    (args.output / "tx94_main_clip_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print("LINKEDIN_MAIN_CLIP_READY", json.dumps({
        "id": case["id"], "video": str(output),
        "duration": manifest["mp4_duration_seconds"],
        "all_sources_resolve": case["all_sources_resolve"],
        "full_source_coverage": case.get("all_expected_sources_covered"),
        "trimmed_wait_time": was_shortened,
    }), flush=True)


if __name__ == "__main__":
    main()
