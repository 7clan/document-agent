"""Merge only first completed blind answers from two separately recorded segments.

No model answers are rewritten, no answered question is repeated, and the
original full-rubric sha256 plus all nine original document hashes must match.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def combine(original: dict, suffix: dict, rubric_bytes: bytes) -> dict:
    questions = json.loads(rubric_bytes)["questions"]
    question_lookup = {q["id"]: q for q in questions}
    required_hash = hashlib.sha256(rubric_bytes).hexdigest()
    if len(questions) != 18 or len(question_lookup) != 18:
        raise ValueError("Must have exactly the frozen eighteen questions")
    if (original.get("ground_truth_sha256") != required_hash
            or suffix.get("ground_truth_sha256") != required_hash):
        raise ValueError("Different question-answer rubric")
    for key in ("engine_ref", "engine_sha", "provider", "model", "document_hashes"):
        if original.get(key) != suffix.get(key):
            raise ValueError("Different run input: " + key)
    if len(original["document_hashes"]) != 9:
        raise ValueError("The recorded corpus does not have exactly nine files")
    if not original.get("video") or not suffix.get("video"):
        raise ValueError("Both real unedited browser video segments are required")

    first = {c["id"]: c for c in original["cases"]}
    second = {c["id"]: c for c in suffix["cases"]}
    if len(first) != len(original["cases"]) or len(second) != len(suffix["cases"]):
        raise ValueError("Duplicate case in source report")
    if any(i not in question_lookup for i in first | second):
        raise ValueError("Unknown question ID")
    if any(i < 13 for i in second):
        raise ValueError("Continuation is not allowed to redo answered questions")
    if any(i >= 13 and c.get("response_captured") for i,c in first.items()):
        raise ValueError("An answer already captured in the continuation range")
    if any(not first.get(i,{}).get("response_captured") for i in range(1,13)):
        raise ValueError("Original first 12 answers are not all captured")
    if any(second[i]["question"] != question_lookup[i]["question"] for i in second):
        raise ValueError("Continuation question differs from frozen gold")
    if any(first[i]["question"] != question_lookup[i]["question"] for i in first):
        raise ValueError("Original question differs from frozen gold")

    result = dict(original)
    merged = []
    for gold in questions:
        id_ = gold["id"]
        prior = first.get(id_)
        later = second.get(id_)
        if prior and prior.get("response_captured"):
            selected = prior
        elif later and later.get("response_captured"):
            selected = later
        else:
            selected = later or prior or {
                "id": id_, "question": gold["question"],
                "category": gold["category"], "critical": gold["critical"],
                "source_documents": gold["source_documents"],
                "response_captured": False, "displayed_answer": "",
                "citations": [], "all_sources_resolve": False,
                "all_expected_sources_covered": False,
            }
        merged.append(selected)

    result["cases"] = merged
    result["case_count"] = 18
    result["recording_segments"] = [
        {"part": "original first-pass",
         "recorded_ids": [x["id"] for x in original["cases"]
                          if x.get("response_captured")],
         "original_video": original["video"],
         "workflow_run": 45219507539},
        {"part": "provider-failure continuation",
         "recorded_ids": [x["id"] for x in suffix["cases"]
                          if x.get("response_captured")],
         "continuation_video": suffix["video"]},
    ]
    result["video"] = "separate_original_and_continuation_uncut_recordings"
    result["video_mp4"] = None
    result["video_note"] = (
        "Two unedited video segments per version, never presented as a "
        "single unbroken 18-question recording. Only Q13–18 were retried "
        "after original Q13 upstream HTTP 503 failures."
    )
    result["summary"] = {
        "attempted": 18,
        "completed_with_answer": sum(bool(c.get("response_captured")) for c in merged),
        "errors": sum(bool(c.get("error")) for c in merged),
        "source_linked": sum(bool(c.get("citations")) for c in merged),
        "all_retrieved_sources_resolve": sum(
            c.get("all_sources_resolve") is True for c in merged),
        "all_expected_sources_present": sum(
            c.get("all_expected_sources_covered") is True for c in merged),
        "critical_completed": sum(
            bool(c.get("critical")) and bool(c.get("response_captured"))
            for c in merged),
        "critical_evidence_covered": sum(
            bool(c.get("critical"))
            and c.get("all_expected_sources_covered") is True for c in merged),
        "semantic_accuracy": "not computed by this merger",
    }
    result["recording_verified"] = bool(
        len(merged) == 18 and all(c.get("response_captured") for c in merged))
    return result


def main() -> int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--rubric",type=Path,required=True)
    p.add_argument("--original-main",type=Path,required=True)
    p.add_argument("--original-pr10",type=Path,required=True)
    p.add_argument("--suffix-main",type=Path,required=True)
    p.add_argument("--suffix-pr10",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    rubric_bytes=args.rubric.read_bytes()
    args.output.mkdir(parents=True,exist_ok=True)
    for side in ("main","pr10"):
        source=json.loads(getattr(args,"original_"+side).read_text())
        continuation=json.loads(getattr(args,"suffix_"+side).read_text())
        merged=combine(source,continuation,rubric_bytes)
        output=args.output/(side+".json")
        output.write_text(json.dumps(merged,indent=2,ensure_ascii=False),
                          encoding="utf-8")
        print("BLIND_CONTINUATION_MERGED",side,
              json.dumps(merged["summary"]),
              "18_complete",merged["recording_verified"],flush=True)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
