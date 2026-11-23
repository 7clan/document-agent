"""No-network regression checks for exact frozen-run resume and transient budgets."""
from __future__ import annotations

import runpy
from pathlib import Path

import pytest


def _load():
    p = Path(__file__).resolve().parents[1] / "scripts" / "run_frozen_acceptance.py"
    return runpy.run_path(str(p))


def _cases():
    return [
        {"id": i, "question": f"Q{i}", "expected_answer": f"A{i}",
         "expected_citations": [f"file.pdf | page {i} | chunk 0"],
         "critical": i == 3}
        for i in range(1, 4)
    ]


def _report():
    return {"provider": "compatible", "model": "google/gemma-4-31b-it",
            "ground_truth_sha256": "frozen",
            "retrieval_mode_requested": "keyword", "case_count": 3,
            "cases": []}


def _saved_entry(case, *, error=None):
    entry = {**case}
    if error is None:
        entry.update({"actual_answer": case["expected_answer"],
                      "verification_status": "evidence_linked",
                      "actual_citations": case["expected_citations"]})
    else:
        entry["provider_error"] = {"http_status": error}
    return entry


def test_resume_reuses_completed_answers_and_retries_only_failed_tail():
    cases = _cases()
    prior = {**_report(), "cases": [
        _saved_entry(cases[0]), _saved_entry(cases[1], error=402)]}
    now = _report()
    offset = _load()["resume_cases"](now, prior, cases)
    assert offset == 1
    assert len(now["cases"]) == 1
    assert now["cases"][0]["actual_answer"] == "A1"
    assert now["resume"] == {
        "previously_answered": 1, "resumed_from_question": 2,
        "checkpoint_compatibility_verified": True,
    }


def test_resume_rejects_changed_frozen_answer_or_model():
    cases = _cases()
    prior = {**_report(), "cases": [_saved_entry(cases[0])]}
    prior["cases"][0]["expected_answer"] = "changed"
    with pytest.raises(ValueError, match="ground truth mismatch"):
        _load()["resume_cases"](_report(), prior, cases)
    prior["cases"][0]["expected_answer"] = "A1"
    prior["model"] = "other"
    with pytest.raises(ValueError, match="incompatible checkpoint: model"):
        _load()["resume_cases"](_report(), prior, cases)


def test_resume_rejects_error_not_last_or_unrelated_error():
    cases = _cases()
    prior = {**_report(), "cases": [
        _saved_entry(cases[0], error=402), _saved_entry(cases[1])]}
    with pytest.raises(ValueError, match="Only a trailing"):
        _load()["resume_cases"](_report(), prior, cases)
    prior["cases"] = [_saved_entry(cases[0], error=400)]
    with pytest.raises(ValueError, match="Only a trailing"):
        _load()["resume_cases"](_report(), prior, cases)


def test_transient_openrouter_in_flight_402_retries_without_spending_more_on_permanent_402(
        monkeypatch):
    fn = _load()["retry_temporary_budget"]
    namespace = fn.__globals__
    attempts = []
    class Transient(Exception):
        status_code = 402
        def __init__(self):
            super().__init__("temporary")
            self.body = {"error": {"metadata": {
                "limit_source": "openrouter_in_flight_budget"}}}
    def transient_once(*_args, **_kwargs):
        attempts.append("called")
        if len(attempts) == 1:
            raise Transient
        return "answer"
    monkeypatch.setitem(namespace, "ask", transient_once)
    monkeypatch.setitem(namespace, "_retry_after_seconds", lambda _exc: 5.0)
    monkeypatch.setattr(namespace["time"], "sleep", lambda _seconds: None)
    assert fn(None, "test", "compatible") == ("answer", 1)
    assert len(attempts) == 2

    class Permanent(Exception):
        status_code = 402
        def __init__(self):
            super().__init__("permanent")
            self.body = {"error": {"metadata": {
                "limit_source": "openrouter_credits"}}}
    attempts.clear()
    def permanent(*_args, **_kwargs):
        attempts.append(1)
        raise Permanent
    monkeypatch.setitem(namespace, "ask", permanent)
    with pytest.raises(Permanent):
        fn(None, "test", "compatible")
    assert len(attempts) == 1
