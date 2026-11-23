"""Optional evidence-bound semantic verification for source-linked model claims.

A semantic pass can confirm support for a paraphrase, but cannot replace
provenance, numerical tools, comprehensive retrieval, or human legal review.
Model failures never convert correct source-linked answers into rejected ones.
"""
from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from .semantic_verifier import (
    VERIFIER_SYSTEM,
    verification_request,
    verify_judgement,
)
from .tools import get_evidence

if TYPE_CHECKING:
    from .agent import Answer

SemanticChecker = Callable[[str, str, dict[str, str]], Any]


def _original_text(payload: dict) -> str:
    if "row" in payload and isinstance(payload["row"], dict):
        return " | ".join(
            f"{key}: {value}" for key, value in payload["row"].items()
            if value is not None
        )
    return str(payload.get("text", ""))


def review_answer(conn: sqlite3.Connection, question: str,
                  answer: Answer, judge: SemanticChecker) -> Answer:
    """Upgrade *only* fully linked claims after an evidence-audited semantic pass.

    A false or unavailable judge result leaves the original, visibly unverified
    source-linked answer available; one fallible language model cannot veto it.
    """
    if answer.verification_status != "evidence_linked" or not answer.claims:
        return answer
    if any(claim.get("status") != "evidence_linked" for claim in answer.claims):
        return answer
    if any(event.get("incomplete") for event in answer.tool_calls):
        return answer

    citations = list(dict.fromkeys(
        cite for claim in answer.claims
        for cite in claim.get("sources", [])
        if isinstance(cite, str) and not cite.endswith(" | document")
    ))
    if not citations or len(citations) > 12:
        return answer
    evidence = {}
    for citation in citations:
        original = _original_text(get_evidence(conn, citation))
        if not original:
            return answer
        evidence[citation] = original

    assertions = "\n".join(str(item["text"]) for item in answer.claims)
    try:
        verdict = judge(question, assertions, evidence)
        supported, checked_refs = verify_judgement(
            verdict, evidence, assertions,
        )
    except Exception as exc:  # noqa: BLE001 - fail safely for external models
        answer.tool_calls.append({
            "name": "semantic_verification", "origin": "application",
            "ok": False, "reason": "Judge unavailable: " + type(exc).__name__,
        })
        return answer

    answer.tool_calls.append({
        "name": "semantic_verification", "origin": "application",
        "ok": supported, "reason": (
            "Independent semantic judgment and literal source quotes verified"
            if supported else "Semantics not confirmed; retain checked citations"
        ), "supporting_citations": checked_refs,
    })
    if supported:
        answer.verification_status = "semantic_supported"
    return answer


def make_provider_judge(provider: str, model: str | None = None
                        ) -> SemanticChecker:
    """Construct an optional separate model call, not a replacement for tools."""
    if provider == "gemini":
        from google import genai
        from google.genai import types

        key = os.getenv("GEMINI_API_KEY", "").strip()
        chosen = (model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")).strip()
        if not key or not chosen:
            raise ValueError("Gemini semantic judge requires configuration")
        client = genai.Client(api_key=key)

        def judge(question: str, answer: str, evidence: dict[str, str]):
            result = client.models.generate_content(
                model=chosen,
                contents=verification_request(question, answer, evidence),
                config=types.GenerateContentConfig(
                    system_instruction=VERIFIER_SYSTEM,
                    response_mime_type="application/json",
                    temperature=0,
                ),
            )
            return result.text
        return judge

    if provider not in {"openai", "groq", "compatible", "ollama_cloud"}:
        raise ValueError("Unsupported semantic verification provider")

    from openai import OpenAI

    from .agent import _compatible_config

    key, chosen, base = _compatible_config(provider, model)
    client = OpenAI(api_key=key, base_url=base or None,
                    timeout=45, max_retries=0)

    def judge(question: str, answer: str, evidence: dict[str, str]):
        result = client.chat.completions.create(
            model=chosen,
            temperature=0,
            messages=[
                {"role": "system", "content": VERIFIER_SYSTEM},
                {"role": "user", "content":
                 verification_request(question, answer, evidence)},
            ],
        )
        return result.choices[0].message.content or ""
    return judge
