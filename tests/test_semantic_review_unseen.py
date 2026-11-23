"""False-negative and false-positive regression tests for semantic regrading."""
from __future__ import annotations

from scripts.semantic_review_unseen import (
    grade_case,
    grade_report,
    normalize_verdict,
    summarize,
)


def example(question="How many compressors and what rating?"):
    return {
        "id": 1, "category": "contract", "critical": False,
        "question": question,
        "expected_answer": "Four 175 kW compressors C-31 through C-34",
        "source_documents": ["Signed_Contract.pdf"],
    }


def recorded(answer="Four compressors rated at 175 kW each.",
             citations=None):
    return {
        "id": 1, "response_captured": True, "displayed_answer": answer,
        "citations": (citations if citations is not None
                      else ["Signed_Contract.pdf | page 1 | chunk 0"]),
        "all_sources_resolve": True,
    }


def test_semantically_correct_paraphrase_not_penalized_for_optional_identifiers():
    result = grade_case(
        example(), recorded(),
        {"label": "correct", "reason": "All asked facts are present"},
    )
    assert result["semantic_label"] == "correct"
    assert result["fully_grounded"]


def test_wrong_approval_cannot_pass_based_on_shared_keywords():
    result = grade_case(
        example("Was the request approved?"),
        recorded("The request was approved."),
        {"label": "incorrect", "reason": "Gold states pending, not approved"},
    )
    assert result["semantic_label"] == "incorrect"
    assert not result["fully_grounded"]


def test_missing_citation_is_separate_from_factual_correctness():
    result = grade_case(
        example(), recorded(citations=[]),
        {"label": "correct", "reason": "Correct quantitative answer"},
    )
    assert result["semantic_label"] == "correct"
    assert not result["source_integrity"]
    assert not result["fully_grounded"]


def test_provider_rate_limit_not_counted_as_wrong_answer():
    report = recorded("")
    report.update(response_captured=False, provider_diagnostic=True,
                  provider_http_status=429)
    result = grade_case(example(), report, None)
    assert result["semantic_label"] == "provider_blocked"
    assert not result["judge_completed"]
    assert summarize([result])["incorrect"] == 0


def test_unknown_judge_response_remains_unreviewed():
    result = grade_case(example(), recorded(), "This looks okay")
    assert result["semantic_label"] == "unreviewed"
    assert not result["judge_completed"]
    assert not result["fully_grounded"]


def test_judge_crash_does_not_become_semantic_failure():
    rubric = {"questions": [example()]}
    report = {"engine_ref": "main", "cases": [recorded()]}

    def fail(_item, _actual):
        raise RuntimeError("429")

    result = grade_report(rubric, report, fail)
    assert result["summary"]["captured"] == 1
    assert result["summary"]["unreviewed"] == 1
    assert result["summary"]["incorrect"] == 0
    assert result["summary"]["semantic_accuracy_among_judged"] is None


def test_partial_answer_kept_distinct_from_incorrect():
    result = grade_case(
        example("List the ratings and quantities for all four compressors"),
        recorded("The compressors are 175 kW."),
        {"label": "partial", "reason": "Quantity is missing"},
    )
    assert summarize([result])["partial"] == 1
    assert not result["fully_grounded"]


def test_invalid_judgement_cannot_promote_result():
    assert normalize_verdict({"label": "pass"})["label"] == "unreviewed"
    assert normalize_verdict("{bad")["label"] == "unreviewed"
    assert normalize_verdict({"label": "correct"})["label"] == "correct"
