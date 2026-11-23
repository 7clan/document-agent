"""Independent prespecified fact/source rubric for real browser answers."""
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def assess(report: dict, rubric: dict) -> dict:
    observations = {case["id"]: case for case in report.get("cases", [])}
    cases = []
    for expected in rubric["questions"]:
        obs = observations.get(expected["id"], {})
        answer = obs.get("displayed_answer", "")
        completed = bool(obs.get("response_captured"))
        missing = [pattern for pattern in expected["required"]
                   if not re.search(pattern, answer, re.IGNORECASE)]
        forbidden = [pattern for pattern in expected["forbidden"]
                     if re.search(pattern, answer, re.IGNORECASE)]
        citations = obs.get("citations", [])
        required_docs = expected["source_documents"]
        docs_covered = bool(required_docs) and all(
            any(c == d or c.startswith(d + " | ") for c in citations)
            for d in required_docs)
        citations_verified = obs.get("all_sources_resolve") is True
        fact_pass = completed and not missing and not forbidden
        grounded_pass = fact_pass and (
            not required_docs or (docs_covered and citations_verified))
        cases.append({
            "id": expected["id"],
            "category": expected["category"],
            "critical": expected["critical"],
            "question": expected["question"],
            "expected": expected["expected_answer"],
            "observed": answer,
            "observed_sources": citations,
            "required_documents": required_docs,
            "completed": completed,
            "fact_rubric_pass": bool(fact_pass),
            "source_documents_covered": bool(docs_covered),
            "citations_verified": bool(citations_verified),
            "strict_grounded_pass": bool(grounded_pass),
            "missing_regex": missing,
            "forbidden_regex_matched": forbidden,
            "provider_http_status": obs.get("provider_http_status"),
            "provider_error": obs.get("error"),
        })
    def total(test):
        return sum(bool(test(x)) for x in cases)
    return {
        "engine": report.get("engine_ref"),
        "sha": report.get("engine_sha"),
        "model": report.get("model"),
        "provider": report.get("provider"),
        "document_hashes": report.get("document_hashes"),
        "question_hash": report.get("ground_truth_sha256"),
        "video": report.get("video"),
        "video_mp4": report.get("video_mp4"),
        "cases": cases,
        "summary": {
            "questions": len(cases),
            "captured": total(lambda x:x["completed"]),
            "factual_rubric": total(lambda x:x["fact_rubric_pass"]),
            "strict_fact_and_citations": total(lambda x:x["strict_grounded_pass"]),
            "critical_total": total(lambda x:x["critical"]),
            "critical_factual": total(lambda x:x["critical"] and x["fact_rubric_pass"]),
            "critical_strict": total(lambda x:x["critical"] and x["strict_grounded_pass"]),
        },
    }


def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument("--baseline",type=Path,required=True)
    p.add_argument("--candidate",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    rubric=json.loads((ROOT/"evaluation/blind_aquifer_questions.json").read_text())
    reports={}
    for name,path in (("main",args.baseline),("candidate",args.candidate)):
        if path.exists():
            reports[name]=assess(json.loads(path.read_text()),rubric)
            (args.output/(name+"_graded.json")).write_text(
                json.dumps(reports[name],ensure_ascii=False,indent=2))
    if len(reports)!=2:
        print("UNSEEN_AB_PARTIAL no_complete_pair")
        return 1
    a,b=reports["main"],reports["candidate"]
    common=(a["document_hashes"]==b["document_hashes"] and
            a["question_hash"]==b["question_hash"] and
            a["model"]==b["model"] and a["provider"]==b["provider"])
    headings=[
        "# AQ-73 unseen document intelligence interview",
        "",
        "Original main compared with PR #10 on the same unseen aquifer monitoring project.",
        "Both were run through the actual Streamlit UI with the same tool-capable model.",
        "This rubric was fixed before model calls and has not been modified after results.",
        "",
        "Same source files, question list, model and provider: "+str(common),
        "Old commit: "+a["sha"],"New commit: "+b["sha"],
        "Model: "+a["provider"]+" / "+a["model"],
        "",
        "## Genuine recorded outcomes",
        "",
        "| Metric | Old main | New PR #9 |",
        "|---|---:|---:|",
    ]
    for label,key in [
        ("Answers actually captured","captured"),
        ("Facts matching fixed rubrics","factual_rubric"),
        ("Factual rubric and all original document citations","strict_fact_and_citations"),
        ("Critical factual rubric","critical_factual"),
        ("Critical factual rubric with complete citations","critical_strict"),
    ]:
        headings.append("| "+label+" | "+str(a["summary"][key])+" | "+
                        str(b["summary"][key])+" |")
    headings.extend([
        "",
        "## Interpretation",
        ("The regex rubric tests prespecified facts and required source-document "
         "coverage. It is not a substitute for human semantic entailment grading. "
         "Provider failures and missing citations are never counted as correct."),
        "Partial videos are not represented as complete interviews.",
        "",
        "## Original question-by-question examiner transcript",
    ])
    with (args.output/"unseen_paired_answers.csv").open(
            "w",newline="",encoding="utf-8-sig") as stream:
        writer=csv.writer(stream)
        writer.writerow(["case","critical","question","expected",
                         "main_actual","new_actual","main_factual","new_factual",
                         "main_strict","new_strict","main_sources","new_sources"])
        for old,new in zip(a["cases"],b["cases"]):
            writer.writerow([old["id"],old["critical"],old["question"],
                old["expected"],old["observed"],new["observed"],
                old["fact_rubric_pass"],new["fact_rubric_pass"],
                old["strict_grounded_pass"],new["strict_grounded_pass"],
                " ; ".join(old["observed_sources"]),
                " ; ".join(new["observed_sources"])])
            headings.extend([
                "",
                "### Case "+str(old["id"])+": "+old["question"],
                "",
                "Expected: "+old["expected"],
                "",
                "Old main answer: "+(old["observed"] or "[not captured]"),
                "",
                "Old citations: "+(", ".join(old["observed_sources"]) or "[none]"),
                "",
                "New PR #9 answer: "+(new["observed"] or "[not captured]"),
                "",
                "New citations: "+(", ".join(new["observed_sources"]) or "[none]"),
                "",
                "Rubric old/new: "+str(old["fact_rubric_pass"])+"/"+
                str(new["fact_rubric_pass"])+
                "; strict original-source old/new: "+
                str(old["strict_grounded_pass"])+"/"+
                str(new["strict_grounded_pass"]),
            ])
    (args.output/"RESULTS.md").write_text("\n".join(headings)+"\n")
    print("UNSEEN_AB_RESULTS",json.dumps({
        "fair_inputs":common,"old":a["summary"],"new":b["summary"],
        "uncut_video_pair":bool(a["video"] and b["video"]),
    }),flush=True)
    return 0 if common and bool(a["video"] and b["video"]) else 1


if __name__=="__main__":
    raise SystemExit(main())
