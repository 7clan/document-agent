"""Resume semantic labels without rejudging prior cases or falsifying failures."""
from __future__ import annotations

import hashlib
import json

import pytest

from scripts.resume_semantic_review import resume, verify_seed


def seed():
    rubric = {"questions": [
        {"id": 1, "question": "How many?", "expected_answer": "Four"},
        {"id": 2, "question": "What rating?", "expected_answer": "175 kW"},
    ]}
    data = json.dumps(rubric).encode()
    digest = hashlib.sha256(data).hexdigest()

    def result(side):
        cases = [
            {"id": 1, "question": "How many?", "reference": "Four",
             "answer": "4", "captured": True, "semantic_label": "correct",
             "semantic_reason": "Previously verified",
             "source_integrity": True,
             "reference_document_coverage": True,
             "judge_completed": True, "fully_grounded": True},
            {"id": 2, "question": "What rating?", "reference": "175 kW",
             "answer": "175 kW", "captured": True,
             "semantic_label": "unreviewed", "semantic_reason": "API 429",
             "source_integrity": True,
             "reference_document_coverage": side == "main",
             "judge_completed": False, "fully_grounded": False},
        ]
        return {"cases": cases, "question_hash": digest,
                "document_hashes": {"contract.pdf": "abc"},
                "model": "model", "provider": "compatible", "summary": {}}
    return {
        "judge": "openrouter/google/gemma-4-31b-it",
        "fair_inputs": True, "rubric_sha256": digest,
        "results": {"main": result("main"), "candidate": result("candidate")},
    }, data, rubric


def test_resume_only_calls_unreviewed_cases_and_retains_seed():
    prior, raw, rubric = seed()
    verify_seed(prior, raw, prior["judge"])
    observed = []
    calls = []

    def judge(item, answer):
        calls.append((item["id"], answer))
        return {"label": "correct", "reason": "Equivalent"}

    result = resume(prior, rubric, judge, max_calls=8, pause_seconds=0,
                    on_progress=lambda state: observed.append(True))
    assert calls == [(2, "175 kW"), (2, "175 kW")]
    assert result["resume"]["started_from_completed_judgments"] == 2
    assert result["resume"]["new_completed_judgments"] == 2
    assert result["results"]["main"]["summary"]["correct"] == 2
    assert result["results"]["candidate"]["summary"]["fully_grounded"] == 1
    assert len(observed) >= 2
    assert result["results"]["main"]["cases"][0]["semantic_reason"] == "Previously verified"


def test_quota_exhaustion_stops_without_fabricating_scores():
    prior, _, rubric = seed()
    calls = []

    class PaymentRequired(Exception):
        status_code = 402

    def exhausted(item, answer):
        calls.append(True)
        raise PaymentRequired("no credits")

    result = resume(prior, rubric, exhausted, pause_seconds=0)
    assert calls == [True]
    assert result["resume"]["stop_reason"] == "quota_or_provider_blocked"
    assert result["resume"]["new_completed_judgments"] == 0
    assert result["results"]["candidate"]["summary"]["unreviewed"] == 1
    assert result["results"]["main"]["summary"]["unreviewed"] == 1


def test_one_rate_limit_can_recover_after_cooldown():
    prior, _, rubric = seed()
    calls = []
    slept = []

    class TooManyRequests(Exception):
        status_code = 429

    def first_limited(item, answer):
        calls.append(item["id"])
        if len(calls) == 1:
            raise TooManyRequests("slow down")
        return {"label": "correct", "reason": "OK"}

    result = resume(prior, rubric, first_limited, max_calls=4,
                    pause_seconds=0, sleeper=lambda sec: slept.append(sec))
    assert calls == [2, 2, 2]
    assert slept == [50]
    assert result["resume"]["new_completed_judgments"] == 2


def test_frozen_reference_change_is_rejected():
    prior, raw, _ = seed()
    with pytest.raises(ValueError):
        verify_seed(prior, raw.replace(b"175 kW", b"180 kW"), prior["judge"])
    with pytest.raises(ValueError):
        verify_seed(prior, raw, "openrouter/some-other-model")
