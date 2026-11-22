"""Two bounded, application-owned attempts to repair grounded answers.

The ledger authenticates locations. It never infers that a passage proves a
contractual interpretation; that remains visibly source linked.
"""
from __future__ import annotations

import os
import re
import sqlite3
from collections.abc import Callable
from typing import TYPE_CHECKING

from .claim_verifier import normalize
from .evidence_ledger import build_ledger
from .query_plan import QueryPlan
from .tools import search_documents

if TYPE_CHECKING:
    from .agent import Answer


def _observed(answer: Answer) -> list[str]:
    citations = list(answer.sources)
    if answer.structured:
        citations.extend(answer.structured.get("candidate_sources", []))
    for event in answer.tool_calls:
        if event.get("name") == "evidence_handoff":
            citations.extend(event.get("citations", []))
    return list(dict.fromkeys(citations))


def _diagnosis(plan: QueryPlan, answer: Answer) -> list[str]:
    issues: list[str] = []
    if (answer.verification_status != "deterministically_verified" and
            not any(event.get("name") in plan.required_operations
                    for event in answer.tool_calls)):
        issues.append("tool_usage")
    if not answer.sources and answer.verification_status != "deterministically_verified":
        issues.append("missing_evidence")
    if answer.claims:
        for claim in answer.claims:
            if claim.get("status") == "unverified":
                reason = str(claim.get("reason", "")).casefold()
                if "cited source" in reason or "reference" in reason:
                    issues.append("citation")
                elif any(word in reason for word in ("date", "number", "amount",
                                                    "identifier")):
                    issues.append("unsupported_fact")
                else:
                    issues.append("unsupported_reasoning")
    if plan.exhaustive and any(event.get("incomplete") for event in answer.tool_calls):
        issues.append("incomplete_coverage")
    if any(event.get("name") in {"source_linking", "claim_validation"}
           and not event.get("ok", True) for event in answer.tool_calls):
        issues.append("answer_format_or_citation")
    return list(dict.fromkeys(issues))


def _search_terms(question: str, identifiers: tuple[str, ...]) -> list[str]:
    if identifiers:
        return list(identifiers[:2])
    words = [word for word in re.findall(r"[\w-]+", question)
             if len(word) > 3 and word.casefold() not in {
                 "which", "what", "where", "when", "does", "these", "those",
                 "from", "with", "this", "that", "have", "been", "about"}]
    return [" ".join(words[:6])] if words else []


def _link_unique_exact_quotes(answer: Answer, ledger: dict) -> int:
    """Attach an omitted citation only for a unique, literal source phrase."""
    linked = 0
    for claim in answer.claims or []:
        if (claim.get("status") != "unverified" or claim.get("had_supports")
                or claim.get("sources")):
            continue
        statement = str(claim.get("text", "")).strip()
        if len(statement) < 12:
            continue
        needle = normalize(statement)
        matching = [record for record in ledger.values()
                    if needle and needle in normalize(record.original())]
        if len(matching) != 1:
            continue
        record = matching[0]
        claim["status"] = "evidence_linked"
        claim["sources"] = [record.source_id]
        claim["quotes"] = [{"citation": record.source_id,
                            "quote": record.original()[:350]}]
        claim["reason"] = "Exact original phrase; interpretation not independently verified"
        answer.sources = list(dict.fromkeys([*answer.sources, record.source_id]))
        old = f"- {statement} *(source reference unavailable)*"
        new = f"- {statement} — {record.source_id}"
        answer.text = answer.text.replace(old, new, 1)
        linked += 1
    if (linked and answer.claims and all(claim.get("status") == "evidence_linked"
                                         for claim in answer.claims)
            and not (answer.structured or {}).get("candidate_sources")):
        answer.verification_status = "evidence_linked"
    return linked


def _append_original_excerpts(answer: Answer, ledger: dict) -> None:
    answer.text += ("\n\nRecovery could not establish every claim. "
                    "Review the retrieved original locations below.")
    excerpts = [f"- {record.original()[:280]} — {record.source_id}"
                for record in ledger.values() if record.original().strip()][:3]
    if excerpts:
        answer.text += ("\n\nOriginal source excerpts (not a verified interpretation):\n"
                        + "\n".join(excerpts))


def recover_answer(
    conn: sqlite3.Connection, question: str, plan: QueryPlan, answer: Answer,
    regenerate: Callable[[list[str]], Answer] | None = None,
) -> Answer:
    """Retrieve locally, then make at most one compact same-provider correction.

    The first attempt is a targeted local read. The optional second attempt
    asks the same provider to use authenticated passages; it does not replay
    the tool history or accept unparsed output as evidence.
    """
    answer.tool_calls.insert(0, plan.audit())
    issues = _diagnosis(plan, answer)
    if not issues or answer.verification_status == "deterministically_verified":
        return answer
    prior_events = {"evidence_retry", "format_retry", "gemini_format_recovery",
                    "provider_parse_recovery", "provider_transient_recovery",
                    "structured_output_fallback", "tool_usage_retry"}
    spent = min(2, sum(event.get("name") in prior_events for event in answer.tool_calls))
    answer.tool_calls.append({"name": "recovery_diagnosis", "origin": "application",
                              "ok": True, "issues": issues, "prior_attempts": spent})
    if spent >= 2:
        _append_original_excerpts(answer, build_ledger(conn, _observed(answer)))
        answer.text += "\n\nRecovery budget exhausted."
        return answer
    observed = _observed(answer)
    ledger = build_ledger(conn, observed)
    needs_retrieval = any(issue in issues for issue in (
        "missing_evidence", "incomplete_coverage", "tool_usage"))
    local_attempt = needs_retrieval or bool(answer.claims)
    if needs_retrieval:
        terms = _search_terms(question, plan.identifiers)
        scope = plan.document_scope[0] if plan.scope_kind == "named" and len(
            plan.document_scope) == 1 else ""
        for term in terms[:2]:
            result = search_documents(conn, term, limit=8, file=scope,
                                      mode=os.getenv("DOCUMENT_AGENT_RETRIEVAL_MODE", "keyword"))
            found = [item["citation"] for item in result.get("results", [])
                     if isinstance(item.get("citation"), str)]
            observed.extend(found)
            answer.tool_calls.append({
                "name": "recovery_retrieval", "origin": "application", "ok": "error" not in result,
                "attempt": spent + 1,
                "query_kind": "exact_identifier" if plan.identifiers else "question_terms",
                "source_count": len(found), "incomplete": bool(result.get("incomplete")),
            })
        ledger = build_ledger(conn, observed)
    exact_links = _link_unique_exact_quotes(answer, ledger)
    if exact_links:
        answer.tool_calls.append({"name": "recovery_exact_link", "origin": "application",
                                  "ok": True, "attempt": spent + 1, "count": exact_links})
    if ledger and answer.verification_status != "deterministically_verified":
        answer.structured = dict(answer.structured or {})
        candidates = list(dict.fromkeys([
            *answer.structured.get("candidate_sources", []), *ledger.keys()]))
        answer.structured["candidate_sources"] = candidates[:30]
    if (regenerate is not None and ledger and answer.verification_status == "unverified"
            and spent + int(local_attempt) < 2
            and any(issue in issues for issue in (
                "citation", "answer_format_or_citation", "missing_evidence",
                "tool_usage", "unsupported_fact"))):
        try:
            corrected = regenerate(list(ledger)[:8])
        except Exception as exc:  # noqa: BLE001 - provider errors remain bounded
            answer.tool_calls.append({"name": "recovery_regeneration", "origin": "application",
                                      "ok": False, "attempt": spent + int(local_attempt) + 1,
                                      "error_type": type(exc).__name__})
        else:
            recovery_reads = [event for event in answer.tool_calls
                              if event.get("name") == "recovery_retrieval"]
            if not any(event.get("name") == "query_plan" for event in corrected.tool_calls):
                corrected.tool_calls.insert(0, plan.audit())
            if not any(event.get("name") == "recovery_retrieval"
                       for event in corrected.tool_calls):
                corrected.tool_calls[1:1] = recovery_reads
            old_linked = sum(claim.get("status") == "evidence_linked"
                             for claim in answer.claims or [])
            new_linked = sum(claim.get("status") == "evidence_linked"
                             for claim in corrected.claims or [])
            improved = new_linked > old_linked or (new_linked == old_linked and
                                                   len(corrected.sources) > len(answer.sources))
            event = {"name": "recovery_regeneration", "origin": "application",
                     "ok": True, "attempt": spent + int(local_attempt) + 1,
                     "source_count": len(ledger),
                     "accepted": improved}
            if improved:
                corrected.tool_calls.append(event)
                answer = corrected
            else:
                answer.tool_calls.append(event)
    if answer.verification_status == "unverified" and ledger:
        _append_original_excerpts(answer, ledger)
    return answer
