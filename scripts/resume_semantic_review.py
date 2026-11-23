"""Resume an interrupted semantic review without changing existing judgments.

Only re-query previously UNREVIEWED answers. The frozen question rubric,
original answers, citation metrics, and successful judge labels are immutable.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

if __package__:
    from .semantic_review_unseen import make_model_judge, normalize_verdict, summarize
else:
    from semantic_review_unseen import make_model_judge, normalize_verdict, summarize


def verify_seed(seed: dict, rubric_bytes: bytes, judge_identity: str) -> dict:
    if (seed.get("fair_inputs") is not True
            or seed.get("judge") != judge_identity
            or seed.get("rubric_sha256") != hashlib.sha256(rubric_bytes).hexdigest()):
        raise ValueError("Judge identity or frozen question hash differs from seed")
    rubric = json.loads(rubric_bytes)
    by_id = {x["id"]: x for x in rubric["questions"]}
    if len(by_id) != len(rubric["questions"]):
        raise ValueError("Duplicate rubric questions")
    results = seed.get("results", {})
    if set(results) != {"main", "candidate"}:
        raise ValueError("Seed must contain the same two engine recordings")
    main = results["main"]
    candidate = results["candidate"]
    if (main.get("question_hash") != candidate.get("question_hash")
            or main.get("document_hashes") != candidate.get("document_hashes")
            or main.get("model") != candidate.get("model")
            or main.get("provider") != candidate.get("provider")):
        raise ValueError("Baseline and candidate recordings are not comparable")
    if main.get("question_hash") != seed["rubric_sha256"]:
        raise ValueError("Recorded question set does not match frozen rubric")
    for engine in ("main", "candidate"):
        cases = results[engine].get("cases", [])
        if {x["id"] for x in cases} != set(by_id) or len(cases) != len(by_id):
            raise ValueError("Missing or duplicate case in " + engine)
        for case in cases:
            gold = by_id[case["id"]]
            if (case.get("question") != gold["question"]
                    or case.get("reference") != gold["expected_answer"]):
                raise ValueError("Question or expected answer has changed")
    return rubric


def resume(seed: dict, rubric: dict, judge: Callable[[dict, str], Any],
           *, max_calls: int = 30, pause_seconds: float = 7,
           on_progress: Callable[[dict], None] | None = None,
           sleeper: Callable[[float], None] = time.sleep) -> dict:
    by_id = {x["id"]: x for x in rubric["questions"]}
    previous = sum(
        case["semantic_label"] in {"correct", "partial", "incorrect"}
        for side in ("main", "candidate")
        for case in seed["results"][side]["cases"]
    )
    requests = 0
    new_judgments = 0
    errors: list[dict] = []
    stopped = ""
    for side in ("main", "candidate"):
        for case in seed["results"][side]["cases"]:
            if case["semantic_label"] != "unreviewed" or not case["captured"]:
                continue
            if requests >= max_calls:
                stopped = "request_budget"
                break
            gold = by_id[case["id"]]
            success = False
            for attempt in range(2):
                if requests >= max_calls:
                    stopped = "request_budget"
                    break
                requests += 1
                try:
                    verdict = normalize_verdict(judge(gold, case["answer"]))
                    if verdict["label"] in {"correct", "partial", "incorrect"}:
                        case["semantic_label"] = verdict["label"]
                        case["semantic_reason"] = verdict["reason"]
                        case["judge_completed"] = True
                        case["fully_grounded"] = (
                            verdict["label"] == "correct"
                            and case["source_integrity"]
                            and case["reference_document_coverage"]
                        )
                        new_judgments += 1
                        success = True
                        print(
                            "REVIEWED", side, case["id"], verdict["label"],
                            "requests", requests, flush=True,
                        )
                    else:
                        case["semantic_reason"] = verdict["reason"]
                        print("UNREVIEWED_JUDGE_RESPONSE", side, case["id"], flush=True)
                    break
                except Exception as exc:  # noqa: BLE001 - external model failures
                    status = getattr(exc, "status_code", None)
                    response = getattr(exc, "response", None)
                    limit_source = None
                    retry_after = None
                    if response is not None:
                        try:
                            body = response.json()
                            metadata = body.get("error", {}).get("metadata", {})
                            limit_source = metadata.get("limit_source")
                            header = response.headers.get("retry-after")
                            retry_after = int(float(header)) if header else None
                        except (AttributeError, TypeError, ValueError):
                            pass
                    errors.append({
                        "engine": side, "id": case["id"], "http_status": status,
                        "limit_source": limit_source,
                        "error_type": type(exc).__name__, "attempt": attempt + 1,
                    })
                    print(
                        "JUDGE_PROVIDER_ERROR", side, case["id"],
                        "status", status, "limit_source", limit_source,
                        "attempt", attempt + 1, flush=True,
                    )
                    temporary = (
                        status == 429 or
                        (status == 402 and limit_source ==
                         "openrouter_in_flight_budget")
                    )
                    if temporary and attempt == 0 and requests < max_calls:
                        # Transient in-flight budget holds release after settlement.
                        # Respect the provider header with a bounded wait.
                        delay = min(100, max(20, (retry_after or 40) + 4))
                        print("TEMPORARY_QUOTA_COOLDOWN_SECONDS", delay, flush=True)
                        sleeper(delay)
                        continue
                    # Spent key caps or insufficient account credits are not
                    # solved by repeatedly submitting billable requests.
                    stopped = ("quota_or_provider_blocked" if status in
                               (401, 402, 403, 404, 429) else "judge_error")
                    break
            if on_progress:
                on_progress(seed)
            if stopped:
                break
            if success and pause_seconds:
                sleeper(pause_seconds)
        if stopped:
            break

    for side in ("main", "candidate"):
        cases = seed["results"][side]["cases"]
        seed["results"][side]["summary"] = summarize(cases)
    seed["resume"] = {
        "started_from_completed_judgments": previous,
        "new_completed_judgments": new_judgments,
        "requests_this_attempt": requests,
        "stop_reason": stopped or "all_available_reviews_completed",
        "errors": errors,
        "reviewed_at_utc": datetime.now(UTC).isoformat(),
    }
    if on_progress:
        on_progress(seed)
    return seed


def write_report(seed: dict, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "semantic_review.json").write_text(
        json.dumps(seed, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    with (output / "semantic_review.csv").open(
            "w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.writer(fp)
        writer.writerow([
            "id", "question", "main_answer", "candidate_answer",
            "main_judgment", "candidate_judgment", "main_cited", "candidate_cited",
        ])
        a = seed["results"]["main"]["cases"]
        b = seed["results"]["candidate"]["cases"]
        for left, right in zip(a, b):
            writer.writerow([
                left["id"], left["question"], left["answer"], right["answer"],
                left["semantic_label"], right["semantic_label"],
                left["source_integrity"], right["source_integrity"],
            ])
    summary = {side: seed["results"][side]["summary"]
               for side in ("main", "candidate")}
    (output / "RESUME_RESULTS.md").write_text(
        "# Resumed MQ-46 semantic review\n\n"
        "All prior completed labels were retained; only unreviewed cases "
        "were sent to the same judge. Original source answers and citations "
        "were not modified.\n\n"
        f"Judge: `{seed['judge']}`\n\n"
        f"Old main: `{json.dumps(summary['main'])}`\n\n"
        f"PR #9: `{json.dumps(summary['candidate'])}`\n\n"
        f"Resume metadata: `{json.dumps(seed.get('resume', {'status': 'in_progress'}))}`\n\n"
        "Correctness among judged cases excludes unavailable quota cases. "
        "These model judgments are provisional and need spot audits.\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prior", type=Path, required=True)
    parser.add_argument("--rubric", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--judge-provider", choices=("openrouter", "groq"),
                        default="openrouter")
    parser.add_argument("--judge-model", default="google/gemma-4-31b-it")
    parser.add_argument("--max-calls", type=int, default=30)
    parser.add_argument("--pause-seconds", type=float, default=7)
    args = parser.parse_args()
    if args.max_calls <= 0 or args.pause_seconds < 0:
        parser.error("Max calls must be positive and pause non-negative")
    seed = json.loads(args.prior.read_text(encoding="utf-8"))
    judge_identity = f"{args.judge_provider}/{args.judge_model}"
    rubric = verify_seed(seed, args.rubric.read_bytes(), judge_identity)
    model_judge = make_model_judge(args.judge_provider, args.judge_model)
    result = resume(
        seed, rubric, model_judge, max_calls=args.max_calls,
        pause_seconds=args.pause_seconds,
        on_progress=lambda state: write_report(state, args.output),
    )
    print(
        "RESUMED_SEMANTIC_REVIEW",
        json.dumps({
            "resume": result["resume"],
            "scores": {side: result["results"][side]["summary"]
                       for side in ("main", "candidate")},
        }), flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
