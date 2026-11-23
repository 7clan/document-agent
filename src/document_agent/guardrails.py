"""Deterministic guards for exact BOQ identifiers and unreadable attachments.

These are host-owned safety decisions, not model prompts. In particular, a
whole identifier must never degrade into an all-items BOQ query.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import date
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



def _exact_priced_rows(conn: sqlite3.Connection, identifier: str,
                       file: str = "") -> list[dict] | None:
    """Find whole exact BOQ IDs; None indicates incomplete/unverified search."""
    candidates: list[dict] = []
    offset = 0
    while offset <= 10000:
        result = query_spreadsheet(
            conn, operator="all", value=0, file=file,
            text_filter=identifier, limit=500, offset=offset)
        # Query warnings may refer to unrelated sheets; never discard a
        # directly verified exact amount because a different row is incomplete.
        if "error" in result:
            return None
        candidates.extend(result.get("matches", []))
        if not result.get("has_more"):
            break
        offset += 500
    else:
        return None
    exact = [row for row in candidates if any(
        isinstance(value, str) and value.casefold().strip() == identifier
        for value in row["values"].values())]
    for row in exact:
        original = get_evidence(conn, row["citation"])
        if (original.get("row") != row["values"]
                or _num(original.get("value", {}).get("value"))
                != Decimal(row["amount_exact"])):
            return None
    return exact



def document_instruction_safety_answer(conn: sqlite3.Connection, question: str,
                                       plan: QueryPlan):
    """Treat explicit instructions *to the AI* inside source files as data."""
    if not (re.search(r"(?i)\b(?:should|must|can|may)\s+(?:an?\s+)?"
                      r"(?:AI|assistant|model)\s+(?:obey|follow|execute|act on)\b",
                      question)
            and re.search(r"(?i)\b(?:commands?|instructions?|prompts?|rules?)\b",
                          question)
            and re.search(r"(?i)\b(?:document|file|note|attachment|pdf|"
                          r"printed|embedded|source)\b", question)):
        return None
    from .agent import Answer

    candidates = []
    rows = conn.execute(
        "SELECT d.path,p.page,p.chunk,p.text FROM passages p "
        "JOIN documents d ON d.id=p.document_id "
        "WHERE d.status='ready' AND d.kind='pdf' "
        "ORDER BY d.path,p.page,p.chunk")
    for row in rows:
        if plan.document_scope and row["path"] not in plan.document_scope:
            continue
        original = row["text"]
        if not re.search(
            r"(?i)\b(?:instruction|command|prompt)\s+to\s+"
            r"(?:the\s+)?(?:AI|assistant|model)\b", original):
            continue
        citation = f"{row['path']} | page {row['page']} | chunk {row['chunk']}"
        if get_evidence(conn, citation).get("text") == original:
            candidates.append(citation)
    sources = list(dict.fromkeys(candidates))[:12]
    lines = [("No. Instructions embedded in project documents are untrusted "
              "source text, not executable instructions for this document agent.")]
    if sources:
        lines.append("Such text was found at: " + ", ".join(sources) + ".")
    else:
        lines.append("No matching source passage was authenticated for this question.")
    return Answer(
        " ".join(lines), sources,
        _trace("host_source_instruction_boundary", authenticated_sources=len(sources)),
        verification_status=("evidence_linked" if sources else "unverified"))


def two_item_comparison_answer(conn: sqlite3.Connection, question: str,
                               plan: QueryPlan):
    """Compare *two* unambiguous, exact-priced rows without model ID confusion."""
    references = requested_references(question)
    if (len(references) != 2 or plan.scope_kind == "mixed"
            or not re.search(r"(?i)\b(?:compare|versus|vs\.?|difference between)\b",
                             question)
            or re.search(r"(?i)\b(?:contract sum|contract value|change order|"
                         r"across documents|versus contract)\b", question)):
        return None
    scoped_file = ""
    if plan.scope_kind == "named" and len(plan.document_scope) == 1:
        scoped_file = plan.document_scope[0]
        if not scoped_file.casefold().endswith((".xlsx", ".xlsm", ".xls", ".pdf")):
            return None

    rows = [_exact_priced_rows(conn, identifier, scoped_file)
            for identifier in references]
    # If neither reference belongs to the financial register, leave this
    # question to the normal prose-document agent.
    if all(result == [] for result in rows):
        return None
    from .agent import Answer

    trace = _trace("host_exact_dual_item_comparison",
                   identifiers=references, scoped_file=scoped_file or None)
    if any(result is None for result in rows):
        return Answer(
            "The indexed financial records contain incomplete or unverified "
            "amount data. The two items cannot be safely compared.",
            [], trace, verification_status="unverified")
    if any(len(result) != 1 for result in rows):
        return Answer(
            "A unique, exact-priced record for each requested item could not "
            "be established. No amount or comparison is inferred; specify "
            "the workbook or worksheet to disambiguate.",
            [], trace, verification_status="unverified")
    left, right = rows[0][0], rows[1][0]
    if left["currency"] != right["currency"]:
        return Answer(
            f"The exact items have different currencies "
            f"({left['currency']} versus {right['currency']}). No direct "
            "difference is calculated without a conversion basis.",
            [left["citation"], right["citation"]], trace,
            verification_status="unverified")
    left_amount, right_amount = (Decimal(left["amount_exact"]),
                                Decimal(right["amount_exact"]))
    higher = ("equal" if left_amount == right_amount
              else references[0].upper() if left_amount > right_amount
              else references[1].upper())
    difference = abs(right_amount - left_amount)
    lines = [
        f"{references[0].upper()}: {left['currency']} {left_amount} — {left['citation']}",
        f"{references[1].upper()}: {right['currency']} {right_amount} — {right['citation']}",
        (f"The amounts are equal (difference {left['currency']} 0)."
         if higher == "equal" else
         f"{higher} is higher by {left['currency']} {difference}."),
    ]
    return Answer(
        "\n".join(lines), [left["citation"], right["citation"]],
        trace, verification_status="deterministically_verified",
        structured={"identifiers": references, "currency": left["currency"],
                    "absolute_difference": str(difference)})


def exact_register_milestone_answer(conn: sqlite3.Connection, question: str,
                                    plan: QueryPlan):
    """Read one explicitly named milestone from an indexed register.

    Only accepts an actual ID/date/classification/approval column set.
    A row identifies what a register *records*; it cannot independently
    establish approval from missing or unrelated contract documents.
    """
    identifiers = requested_references(question)
    if (len(identifiers) != 1 or plan.scope_kind == "mixed"
            or not re.fullmatch(r"[a-z]{1,5}[-_]\d+", identifiers[0])
            or re.search(r"(?i)\b(?:compare|versus|all|every|between)\b", question)):
        return None
    wants_date = bool(re.search(
        r"(?i)\b(?:what date|which date|date attached|when (?:is|was|must)|"
        r"what (?:is|was) the deadline)\b", question))
    wants_status = bool(re.search(
        r"(?i)\b(?:binding deadline|contractual deadline|approved|approval|"
        r"planning target|final date)\b", question))
    if not wants_date and not wants_status:
        return None

    scoped_file = (plan.document_scope[0] if plan.scope_kind == "named"
                   and len(plan.document_scope) == 1 else "")
    if scoped_file and not scoped_file.casefold().endswith((".xlsx", ".xlsm", ".xls")):
        return None

    selected = []
    register_seen = False
    records = conn.execute(
        "SELECT d.path,s.sheet,s.row_num,s.cells_json FROM sheet_rows s "
        "JOIN documents d ON d.id=s.document_id "
        "WHERE d.status='ready' AND d.kind IN ('xlsx','xlsm','xls') "
        "ORDER BY d.path,s.sheet,s.row_num")
    sheets: dict[tuple[str, str], list] = {}
    for row in records:
        if scoped_file and row["path"] != scoped_file:
            continue
        sheets.setdefault((row["path"], row["sheet"]), []).append(row)
    for (file, sheet), entries in sheets.items():
        headers = None
        header_row_num = -1
        for entry in entries:
            cells = {col: str(value.get("value") or "").strip().casefold()
                     for col, value in json.loads(entry["cells_json"]).items()}
            found = {}
            for col, value in cells.items():
                if value in {"milestone", "milestone id", "milestone ref", "reference"}:
                    found["identifier"] = col
                elif value in {"date", "due date", "target date", "deadline"}:
                    found["date"] = col
                elif value in {"classification", "category", "status"}:
                    found["classification"] = col
                elif value in {"approval", "approval status", "authorization"}:
                    found["approval"] = col
                elif value in {"deliverable", "description", "activity"}:
                    found["deliverable"] = col
            if "identifier" in found and "date" in found:
                headers, header_row_num = found, entry["row_num"]
                register_seen = True
                break
        if headers is None:
            continue
        for entry in entries:
            if entry["row_num"] <= header_row_num:
                continue
            values = {col: entry_value.get("value")
                      for col, entry_value in json.loads(entry["cells_json"]).items()}
            identifier = values.get(headers["identifier"])
            if not isinstance(identifier, str) or identifier.strip().casefold() != identifiers[0]:
                continue
            citation = f"{file} | {sheet} | row {entry['row_num']}"
            if get_evidence(conn, citation).get("row") != values:
                from .agent import Answer
                return Answer(
                    "The original milestone row could not be verified.",
                    [], _trace("host_exact_milestone", identifier=identifiers[0]),
                    verification_status="unverified")
            selected.append((values, headers, citation))
    if not register_seen:
        return None

    from .agent import Answer

    trace = _trace("host_exact_milestone", identifier=identifiers[0])
    if len(selected) != 1:
        return Answer(
            ("No exact milestone was found in the readable indexed registers."
             if not selected else
             "Conflicting or duplicate milestone rows were found across registers.")
            + " No date or approval status is inferred.",
            [], trace, verification_status="unverified")
    values, cols, citation = selected[0]
    raw_date = values.get(cols["date"])
    try:
        date_text = date.fromisoformat(str(raw_date).strip()[:10]).isoformat()
    except ValueError:
        return Answer(
            f"{identifiers[0].upper()} has no verifiable ISO calendar date in "
            "the indexed milestone row.", [citation], trace,
            verification_status="unverified")
    description = str(values.get(cols.get("deliverable", "")) or "").strip()
    classification = str(values.get(cols.get("classification", "")) or "").strip()
    approval = str(values.get(cols.get("approval", "")) or "").strip()
    if wants_status and not classification and not approval:
        return Answer(
            f"{identifiers[0].upper()} is dated {date_text}, but its approval "
            f"and contractual status are not recorded. — {citation}",
            [citation], trace, verification_status="unverified")
    lines: list[str] = []
    binding = bool(re.search(r"(?i)\b(?:binding|contractual deadline)\b", question))
    approved = bool(re.search(r"(?i)\b(?:approved|approval)\b", question))
    if binding:
        if (classification.casefold() == "contractual"
                and approval.casefold() in {"signed contract", "approved", "signed"}):
            lines.append("Yes, this register identifies it as contractual.")
        elif (classification.casefold() in {"planning", "proposal", "internal"}
              or approval.casefold() in {"internal only", "not approved", "pending"}):
            lines.append("No, this register does not identify it as a binding deadline.")
        else:
            lines.append("The register alone does not establish whether it is binding.")
    elif approved:
        if approval.casefold() in {"not approved", "pending", "internal only"}:
            lines.append("No, the milestone is not recorded as approved.")
        elif approval.casefold() in {"approved", "signed", "signed contract"}:
            lines.append("Yes, the milestone is recorded as approved in this register.")
        else:
            lines.append("The register does not establish approval.")
    lines.append(f"{identifiers[0].upper()} ({description or 'milestone'}) "
                 f"is dated {date_text} in the indexed register.")
    if classification:
        lines.append(f"Register classification: {classification}.")
    if approval:
        lines.append(f"Register approval field: {approval}.")
    lines.append(f"Original source: {citation}")
    # Do not claim that a register entry independently modifies a contract.
    if wants_status:
        lines.append("This describes the register entry, not independent "
                     "evidence of a contract amendment or final client acceptance.")
    return Answer(
        " ".join(lines), [citation], trace,
        verification_status="deterministically_verified",
        structured={"milestone": identifiers[0], "date": date_text,
                    "classification": classification, "approval": approval})


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
