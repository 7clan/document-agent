"""Contract checks for the offline acceptance summary; no LLM requests."""
from __future__ import annotations

import runpy
from pathlib import Path


def _summarize(rows):
    root = Path(__file__).resolve().parents[1]
    script = runpy.run_path(str(root / "scripts" / "run_frozen_acceptance.py"))
    return script["summarize_cases"](rows)


def test_empty_citations_never_count_as_verified_source_citations():
    result = _summarize([
        {"critical": True, "actual_citations": [],
         "all_sources_resolve": True, "all_expected_sources_covered": False,
         "verification_status": "unverified", "model_tool_calls": 1},
        {"critical": False, "actual_citations": ["contract.pdf | page 1 | chunk 0"],
         "all_sources_resolve": True, "all_expected_sources_covered": True,
         "verification_status": "evidence_linked", "model_tool_calls": 2},
        {"critical": True, "provider_error": {"http_status": 402},
         "all_expected_sources_covered": False},
    ])
    assert result["attempted"] == 3
    assert result["answers_with_citations"] == 1
    assert result["answers_without_citations"] == 1
    assert result["verified_source_citations"] == 1
    assert result["provider_errors"] == 1
    assert result["provider_http_402"] == 1
    assert result["critical_attempted"] == 2
    assert result["critical_source_covered"] == 0
    assert result["semantic_correctness"] == "manual review required"


def test_no_citations_does_not_imply_citation_validation():
    result = _summarize([
        {"actual_citations": [], "all_sources_resolve": False,
         "all_expected_sources_covered": True,
         "critical": True, "verification_status": "unverified"},
        {"actual_citations": [], "all_sources_resolve": False,
         "all_expected_sources_covered": True,
         "critical": True, "verification_status": "unverified"},
    ])
    assert result["answers_with_citations"] == 0
    assert result["verified_source_citations"] == 0
    # Intentionally absent evidence may legitimately have zero expected labels.
    assert result["expected_sources_covered"] == 2
    assert result["critical_source_covered"] == 2


def test_provider_429_only_counts_error_not_an_answer():
    result = _summarize([
        {"critical": False, "provider_error": {"http_status": 429,
          "code": "rate_limit"}},
    ])
    assert result["provider_http_429"] == 1
    assert result["answers_without_citations"] == 0
    assert result["verified_source_citations"] == 0


def test_expected_source_metrics_exclude_intentionally_citation_free_questions():
    report = _summarize([
        {"id": 1, "critical": True, "expected_citations": [],
         "actual_citations": [], "all_expected_sources_covered": True,
         "verification_status": "unverified"},
        {"id": 2, "critical": True,
         "expected_citations": ["contract.pdf | page 1 | chunk 0"],
         "actual_citations": ["contract.pdf | page 1 | chunk 0"],
         "all_expected_sources_covered": True,
         "verification_status": "evidence_linked"},
        {"id": 3, "critical": True,
         "expected_citations": ["contract.pdf | page 2 | chunk 0"],
         "actual_citations": ["other.pdf | page 1 | chunk 0"],
         "all_expected_sources_covered": False,
         "verification_status": "evidence_linked"},
        {"id": 4, "critical": False,
         "expected_citations": ["document.docx | paragraph 1"],
         "actual_citations": ["document.docx | paragraph 1"],
         "all_expected_sources_covered": True,
         "verification_status": "evidence_linked"},
    ])
    assert report["expected_sources_covered"] == 3  # old inclusive metric
    assert report["evidence_required_cases"] == 3
    assert report["evidence_required_all_expected_sources"] == 2
    assert report["critical_evidence_required_cases"] == 2
    assert report["critical_evidence_required_all_expected_sources"] == 1
    assert report["citation_free_expected_cases"] == 1
