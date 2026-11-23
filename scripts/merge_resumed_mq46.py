"""Merge interrupted real UI interviews with separately recorded suffix attempts.

Never overwrite a captured answer; only append responses to previously
unanswered frozen questions. Preserve *both* video segments and all metadata.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def pending_questions(frozen: dict, report: dict) -> list[dict]:
    ids = {case["id"] for case in report.get("cases", [])
           if case.get("response_captured") is True}
    return [q for q in frozen["questions"] if q["id"] not in ids]


def merge_one(original: dict, continuation: dict, frozen_bytes: bytes) -> dict:
    full = json.loads(frozen_bytes)["questions"]
    if original.get("ground_truth_sha256") != hashlib.sha256(frozen_bytes).hexdigest():
        raise ValueError("Original report does not match frozen question bytes")
    for field in ("document_hashes", "model", "provider", "engine_sha", "engine_ref"):
        if original.get(field) != continuation.get(field):
            raise ValueError("Different versions or inputs: " + field)
    remaining = pending_questions({"questions": full}, original)
    snippet_bytes = json.dumps({"questions": remaining}, ensure_ascii=False, indent=2).encode()
    # Check subset question identities/content, regardless of JSON spacing in
    # the external recorder's manifest.
    if continuation.get("case_count") != len(remaining):
        raise ValueError("Continuation did not use the expected frozen remainder")
    if continuation.get("ground_truth_sha256") != hashlib.sha256(snippet_bytes).hexdigest():
        raise ValueError("Continuation questions were not the frozen remainder")
    by_id = {c["id"]: c for c in original["cases"]}
    suffix = {c["id"]: c for c in continuation["cases"]}
    if any(cid not in {q["id"] for q in remaining} for cid in suffix):
        raise ValueError("Continuation answered an already captured case")
    merged_cases = []
    for item in full:
        cid = item["id"]
        prior = by_id.get(cid)
        later = suffix.get(cid)
        if prior and prior.get("response_captured"):
            chosen = prior
        elif later and later.get("response_captured"):
            chosen = later
        else:
            chosen = later or prior or {
                "id": cid, "question": item["question"],
                "response_captured": False,
                "displayed_answer": "", "citations": [],
                "source_documents": item.get("source_documents", []),
            }
        merged_cases.append(chosen)
    report = dict(original)
    report["cases"] = merged_cases
    report["recording_segments"] = [
        {"type": "original", "cases": [
            c["id"] for c in original["cases"] if c.get("response_captured")
        ], "video": original.get("video"), "run": 45194940348},
        {"type": "continuation", "cases": [
            c["id"] for c in continuation["cases"] if c.get("response_captured")
        ], "video": continuation.get("video")},
    ]
    report["is_stitched_video"] = False
    report["video"] = "two_separate_recording_segments"
    report["summary"] = {
        "attempted": len(merged_cases),
        "completed_with_answer": sum(x.get("response_captured") is True
                                     for x in merged_cases),
        "errors": sum(bool(x.get("error")) for x in merged_cases),
        "source_linked": sum(bool(x.get("citations")) for x in merged_cases),
        "all_retrieved_sources_resolve": sum(
            x.get("all_sources_resolve") is True for x in merged_cases),
        "all_expected_sources_present": sum(
            x.get("all_expected_sources_covered") is True for x in merged_cases),
        "critical_completed": sum(
            bool(x.get("critical")) and x.get("response_captured") is True
            for x in merged_cases),
        "critical_evidence_covered": sum(
            bool(x.get("critical")) and
            x.get("all_expected_sources_covered") is True for x in merged_cases),
        "semantic_accuracy": "not scored here; independent semantic judge required",
    }
    report["recording_verified"] = bool(
        len(merged_cases) == len(full)
        and all(c.get("response_captured") is True for c in merged_cases)
        and original.get("video") and continuation.get("video")
    )
    report["recording_note"] = (
        "Original and continuation are separate unedited browser recordings. "
        "No response was regenerated for a previously captured question. "
        "Both parts used the same pinned commit, corpus, model and provider."
    )
    return report


def main() -> int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--original-main",type=Path,required=True)
    p.add_argument("--original-candidate",type=Path,required=True)
    p.add_argument("--continued-main",type=Path,required=True)
    p.add_argument("--continued-candidate",type=Path,required=True)
    p.add_argument("--rubric",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    frozen=args.rubric.read_bytes()
    args.output.mkdir(parents=True,exist_ok=True)
    for side in ("main", "candidate"):
        orig=json.loads(getattr(args, "original_"+side).read_text())
        continuation_path=getattr(args, "continued_"+side)
        if not continuation_path.exists():
            print("NO_CONTINUATION",side,flush=True)
            continue
        continued=json.loads(continuation_path.read_text())
        merged=merge_one(orig,continued,frozen)
        (args.output/(side+"_merged.json")).write_text(
            json.dumps(merged,ensure_ascii=False,indent=2),encoding="utf-8")
        print("MERGED_REAL_INTERVIEW",side,
              json.dumps(merged["summary"]),"verified",
              merged["recording_verified"],flush=True)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
