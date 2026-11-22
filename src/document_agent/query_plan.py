"""Small, validated plans for read-only document questions.

The plan records required coverage. It does not try to interpret contract prose.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from typing import Literal

from .claim_verifier import question_parts
from .retrieval_ids import requested_references

Intent = Literal[
    "exact_identifier", "financial_filter", "financial_aggregation",
    "exhaustive_inventory", "date_or_milestone_inventory",
    "approval_or_contract_status", "general_semantic_question",
    "multi_part_question", "missing_information",
]

OPERATIONS = frozenset({"list_documents", "search_documents", "query_spreadsheet",
                        "extract_dates", "get_evidence"})


@dataclass(frozen=True)
class QueryPlan:
    intents: tuple[Intent, ...]
    document_scope: tuple[str, ...]
    scope_kind: Literal["all_indexed", "named", "mixed"]
    required_operations: tuple[str, ...]
    required_evidence_types: tuple[str, ...]
    identifiers: tuple[str, ...]
    exhaustive: bool
    deterministic: bool
    incomplete_blocks_certainty: bool

    def validate(self, indexed_paths: set[str]) -> None:
        if not self.intents or not self.required_operations:
            raise ValueError("A query plan requires an intent and a read-only operation")
        if not set(self.required_operations) <= OPERATIONS:
            raise ValueError("A query plan requested an unavailable operation")
        if not set(self.document_scope) <= indexed_paths:
            raise ValueError("A query plan names a document outside the active index")
        if self.scope_kind == "named" and not self.document_scope:
            raise ValueError("Named scope requires an indexed document")

    def audit(self) -> dict[str, object]:
        """Safe trace metadata: no source text, credentials, or model output."""
        return {
            "name": "query_plan", "ok": True, "origin": "application",
            "intents": list(self.intents), "document_scope": list(self.document_scope),
            "scope_kind": self.scope_kind,
            "required_operations": list(self.required_operations),
            "required_evidence_types": list(self.required_evidence_types),
            "identifiers": list(self.identifiers), "exhaustive": self.exhaustive,
            "deterministic": self.deterministic,
            "incomplete_blocks_certainty": self.incomplete_blocks_certainty,
        }


def plan_question(conn: sqlite3.Connection, question: str) -> QueryPlan:
    """Classify explicit requests without replacing provider interpretation."""
    indexed = [row[0] for row in conn.execute("SELECT path FROM documents ORDER BY path")]
    lower = question.casefold()
    named = tuple(path for path in indexed if path.casefold() in lower)
    parts = question_parts(question)
    mixed = len(named) > 1 or bool(named and len(parts) > 1)
    scope_kind: Literal["all_indexed", "named", "mixed"] = (
        "mixed" if mixed else "named" if named else "all_indexed")
    identifiers = tuple(requested_references(question))
    exhaustive = bool(re.search(r"\b(?:all|every|entire|complete|exhaustive)\b", lower))
    financial = bool(re.search(r"\b(?:boq|cost items?|line items?|unit prices?|"
                               r"extended amounts?|spreadsheets?)\b", lower))
    comparison = bool(re.search(r"\b(?:above|below|over|under|exceed|greater|less|"
                                r"at least|strictly)\b|[<>]", lower))
    aggregation = bool(re.search(r"\b(?:sum|subtotal|total|aggregate)\b", lower))
    dates = bool(re.search(r"\b(?:dates?|deadlines?|milestones?|deliverables?)\b", lower))
    approval = bool(re.search(r"\b(?:approv\w*|authoriz\w*|contractual|binding|"
                               r"propos\w*|planning|pending|excluded?)\b", lower))
    absence = bool(re.search(r"\b(?:absent|missing|not documented|not found|"
                              r"available|phone number|contact details?)\b", lower))
    inventory = bool(re.search(r"\b(?:list|enumerate|which|extract|show)\b", lower))

    intents: list[Intent] = []
    operations: list[str] = []
    evidence: list[str] = []
    if identifiers:
        intents.append("exact_identifier")
        operations.append("search_documents")
        evidence.append("whole_identifier")
    if financial and comparison:
        intents.append("financial_filter")
        operations.append("query_spreadsheet")
        evidence.append("amount_cell")
    if financial and aggregation:
        intents.append("financial_aggregation")
        operations.append("query_spreadsheet")
        evidence.append("amount_cell")
    if dates and (inventory or exhaustive):
        intents.append("date_or_milestone_inventory")
        operations.append("extract_dates")
        evidence.append("dated_source")
        exhaustive = True
    if inventory and re.search(r"\b(?:files?|documents?|formats?)\b", lower):
        intents.append("exhaustive_inventory")
        operations.append("list_documents")
        evidence.append("index_record")
        exhaustive = True
    if approval:
        intents.append("approval_or_contract_status")
        operations.append("search_documents")
        evidence.append("original_passage_or_row")
    if absence:
        intents.append("missing_information")
        operations.extend(("list_documents", "search_documents"))
        evidence.append("coverage_record")
    if len(parts) > 1 or question.count("?") > 1:
        intents.append("multi_part_question")
    if not intents or intents == ["multi_part_question"]:
        intents.append("general_semantic_question")
        operations.append("search_documents")
        evidence.append("original_passage_or_row")
    operations.append("get_evidence")
    deterministic = bool(intents) and all(intent in {
        "financial_filter", "financial_aggregation", "exhaustive_inventory",
    } for intent in intents)
    plan = QueryPlan(
        intents=tuple(dict.fromkeys(intents)), document_scope=named,
        scope_kind=scope_kind, required_operations=tuple(dict.fromkeys(operations)),
        required_evidence_types=tuple(dict.fromkeys(evidence)),
        identifiers=identifiers, exhaustive=exhaustive,
        deterministic=deterministic,
        incomplete_blocks_certainty=exhaustive or absence,
    )
    plan.validate(set(indexed))
    return plan
