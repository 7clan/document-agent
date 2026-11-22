"""Deterministic guards for exact BOQ identifiers and unreadable attachments.

These are host-owned safety decisions, not model prompts. In particular, a
whole identifier must never degrade into an all-items BOQ query.
"""
from __future__ import annotations

import re
import sqlite3
from decimal import Decimal
from typing import TYPE_CHECKING

from .retrieval_ids import requested_references
from .spreadsheet import _num, query_spreadsheet
from .tools import get_evidence

if TYPE_CHECKING:
    from .query_plan import QueryPlan

_CURRENCIES = r"(?:SAR|AED|USD|EUR|GBP)"
_MONEY = re.compile(
    rf"(?i)\b({_CURRENCIES})\s*([\d,]+(?:\.\d+)?)\s*(million|billion|thousand)?\b"
)
_COMPARISON = re.compile(
    r"(?i)\b(?:exceeds?|above|over|under|below|less than|more than|"
    r"greater than|at least|at most|no more than|no less than)\b|[<>]"
)
_FINANCIAL = re.compile(
    r"(?i)\b(?:items?|line items?|amounts?|prices?|costs?|boq|"
    r"extended value|total value|worth|exceeds?|above|below|under|over)\b"
)
_BAD_ATTACHMENT = re.compile(r"(?i)\b(?:damaged|corrupt(?:ed)?|unreadable|failed)\b")
_ATTACHMENT = re.compile(r"(?i)\b(?:attachments?|files?|documents?|pdfs?|workbooks?)\b")
_APPROVAL = re.compile(r"(?i)\b(?:approv\w*|authoriz\w*|establish|prove|confirm)\b")


def _trace(name: str, **details: object) -> list[dict[str, object]]:
    return [{"name": name, "ok": True, "origin": "application", **details}]


def unreadable_attachment_answer(conn: sqlite3.Connection, question: str,
                                 plan: QueryPlan):
    """Never use another readable file to establish contents of a failed attachment."""
    if not (_BAD_ATTACHMENT.search(question) and _ATTACHMENT.search(question)
            and _APPROVAL.search(question)):
        return None
    failures = conn.execute(
        "SELECT path, status FROM documents WHERE status!='ready' "
        "OR (kind='pdf' AND error<>'') ORDER BY path"
    ).fetchall()
    if plan.document_scope:
        failures = [row for row in failures if row["path"] in plan.document_scope]
    if not failures:
        return None
    from .agent import Answer

    names = ", ".join(row["path"] for row in failures)
    return Answer(
        "No approval can be established from the unreadable attachment: "
        f"{names}. The indexed content is unavailable or incomplete. "
        "This does NOT establish that the original attachment contains no approval; "
        "its contents must be inspected or repaired before drawing that conclusion.",
        [], _trace("host_unreadable_attachment", affected_files=len(failures)),
        verification_status="unverified",
    )


def exact_item_answer(conn: sqlite3.Connection, question: str, plan: QueryPlan):
    """Answer a single exact BOQ item from cells or safely report missing evidence.

    A model cannot change the query's scope, item code, operator, or threshold.
    Other question categories, including comparisons to contract prose, keep
    the existing agent path.
    """
    identifiers = requested_references(question)
    if (len(identifiers) != 1 or not _FINANCIAL.search(question)
            or plan.scope_kind == "mixed"
            or re.search(r"(?i)\b(?:contract sum|contract value|change order|"
                         r"across documents|versus contract)\b", question)):
        return None
    identifier = identifiers[0]
    file = ""
    if plan.scope_kind == "named" and len(plan.document_scope) == 1:
        file = plan.document_scope[0]
    if file and not file.casefold().endswith((".xlsx", ".xlsm", ".xls", ".pdf")):
        return None

    from .agent import Answer

    result = query_spreadsheet(conn, operator="all", value=0, file=file,
                               text_filter=identifier, limit=500)
    trace = _trace("host_exact_item_query", identifier=identifier,
                   scoped_file=file or None)
    if "error" in result:
        return Answer("Exact-item amount lookup could not be completed: " + result["error"],
                      [], trace, verification_status="unverified")

    candidates = list(result["matches"])
    offset = 500
    while result["has_more"] and offset <= 10000:
        result = query_spreadsheet(conn, operator="all", value=0, file=file,
                                   text_filter=identifier, limit=500, offset=offset)
        if "error" in result:
            return Answer("Exact-item lookup was interrupted.", [], trace,
                          verification_status="unverified")
        candidates.extend(result["matches"])
        offset += 500
    if result["has_more"]:
        return Answer("Too many matching rows to establish a complete exact-item result. "
                      "Narrow the workbook or worksheet.", [], trace,
                      verification_status="unverified")

    rows = [row for row in candidates if any(
        isinstance(value, str) and value.casefold().strip() == identifier
        for value in row["values"].values())]
    verified = []
    for row in rows:
        evidence = get_evidence(conn, row["citation"])
        if (evidence.get("row") == row["values"]
                and _num(evidence.get("value", {}).get("value"))
                == Decimal(row["amount_exact"])):
            verified.append(row)
    if len(verified) != len(rows):
        return Answer("An exact item was found, but its original amount cell "
                      "could not be verified.", [], trace,
                      verification_status="unverified")
    if not verified:
        return Answer(
            f"No exact item {identifier.upper()} was found in the indexed readable "
            "financial rows. No amount or unrelated BOQ total is attributed to it. "
            "This is not a claim about unreadable or unindexed files.",
            [], trace, verification_status="unverified",
        )

    compare = bool(_COMPARISON.search(question))
    amount_match = _MONEY.search(question)
    if compare and not amount_match:
        return Answer("Please specify a currency and numerical threshold for "
                      f"item {identifier.upper()}.", [], trace,
                      verification_status="unverified")
    operator = "gt"
    target: Decimal | None = None
    currency: str | None = None
    if amount_match:
        currency = amount_match.group(1).upper()
        factor = {None: 1, "thousand": 1000, "million": 1000000,
                  "billion": 1000000000}[amount_match.group(3).lower()
                                          if amount_match.group(3) else None]
        target = Decimal(amount_match.group(2).replace(",", "")) * factor
        if re.search(r"(?i)\b(?:at least|no less than|greater than or equal)\b|>=",
                     question):
            operator = "gte"
        elif re.search(r"(?i)\b(?:at most|no more than|less than or equal)\b|<=",
                       question):
            operator = "lte"
        elif re.search(r"(?i)\b(?:under|below|less than|cheaper)\b|(?<![<])<(?![=])",
                       question):
            operator = "lt"

    lines: list[str] = []
    sources: list[str] = []
    for row in verified:
        original_amount = Decimal(row["amount_exact"])
        row_currency = row["currency"]
        if compare and currency != row_currency:
            return Answer(
                f"Cannot compare item {identifier.upper()} in {row_currency} to "
                f"a {currency} threshold without currency conversion.",
                [row["citation"]], trace, verification_status="unverified",
            )
        text = f"Exact item {identifier.upper()} is {row_currency} {original_amount}"
        if compare and target is not None:
            verdict = {"gt": original_amount > target,
                       "gte": original_amount >= target,
                       "lt": original_amount < target,
                       "lte": original_amount <= target}[operator]
            text = ("Yes. " if verdict else "No. ") + text + (
                f"; threshold {operator} {currency} {target}"
            )
        lines.append(text + f" — {row['citation']}")
        sources.append(row["citation"])
    if len(verified) > 1:
        lines.insert(0, "Multiple exact records were found; no single amount "
                     "or aggregate is inferred. Specify the workbook if needed.")
    return Answer(
        "\n".join(lines), list(dict.fromkeys(sources)),
        trace, structured={"exact_item": identifier, "matching_rows": verified},
        verification_status=("deterministically_verified" if len(verified) == 1
                             else "evidence_linked"),
    )
