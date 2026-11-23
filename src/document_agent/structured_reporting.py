"""Narrow deterministic reports built from complete, independently checked source rows.

Do not infer approval or contractual legal effect from a spreadsheet label.
Ambiguous registers, missing subtotal rows and incomplete amount extraction fail closed.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from .spreadsheet import _num, query_spreadsheet
from .tools import get_evidence

if TYPE_CHECKING:
    from .query_plan import QueryPlan


def _trace(name: str, **kwargs: object) -> list[dict]:
    return [{"name": name, "ok": True, "origin": "application", **kwargs}]


def verified_base_subtotal(conn: sqlite3.Connection, question: str, plan: QueryPlan):
    """Return a reconciled, explicitly reported base subtotal, never a guessed total."""
    if (plan.scope_kind == "mixed"
            or not re.search(r"(?i)\bsubtotal\b", question)
            or not re.search(r"(?i)\bbase\b", question)
            or re.search(r"(?i)\b(?:contract|revised|post[- ]change|compare|equal|same)\b",
                         question)):
        return None
    from .agent import Answer

    sheet_rows = conn.execute(
        "SELECT DISTINCT d.path,s.sheet FROM sheet_rows s "
        "JOIN documents d ON d.id=s.document_id WHERE d.status='ready' "
        "ORDER BY d.path,s.sheet").fetchall()
    possible = [(row["path"], row["sheet"]) for row in sheet_rows
                if re.search(r"(?i)\bbase\b", row["sheet"])
                and not re.search(r"(?i)\b(?:change|variation|approved)\b", row["sheet"])
                and (not plan.document_scope or row["path"] in plan.document_scope)]
    if len(possible) != 1:
        return None
    file, sheet = possible[0]
    trace = _trace("host_reconciled_base_subtotal", file=file, sheet=sheet)
    result = query_spreadsheet(conn, file=file, sheet=sheet, operator="all",
                               value=0, limit=500)
    if ("error" in result or result.get("incomplete")
            or result.get("has_more") or not result.get("matches")
            or len(result.get("matched_amount_sums", {})) != 1):
        return Answer(
            "The base subtotal cannot be verified: the amount rows are incomplete "
            "or have ambiguous currencies.", [], trace,
            verification_status="unverified")
    currency, total_str = next(iter(result["matched_amount_sums"].items()))
    total = Decimal(total_str)
    detail_citations = []
    columns = set()
    for item in result["matches"]:
        citation = item["citation"]
        evidence = get_evidence(conn, citation)
        if (evidence.get("row") != item["values"]
                or _num(evidence.get("value", {}).get("value"))
                != Decimal(item["amount_exact"])):
            return Answer("The base subtotal failed original-cell validation.",
                          [], trace, verification_status="unverified")
        detail_citations.append(citation)
        cell_match = re.search(r"!([A-Z]{1,3})[1-9]\d*$", citation)
        if cell_match is not None:
            columns.add(cell_match.group(1))
    if len(columns) != 1:
        return Answer("No single amount column could be authenticated.",
                      [], trace, verification_status="unverified")
    amount_col = next(iter(columns))
    summary = []
    for row in conn.execute(
        "SELECT s.row_num,s.cells_json FROM sheet_rows s JOIN documents d "
        "ON d.id=s.document_id WHERE d.status='ready' AND d.path=? "
        "AND s.sheet=? ORDER BY s.row_num", (file, sheet)):
        cells = json.loads(row["cells_json"])
        descriptor = " ".join(str(c.get("value") or "").strip().casefold()
                              for col, c in cells.items() if col != amount_col)
        if not re.search(r"\bsubtotal\b|\bsub[- ]total\b", descriptor):
            continue
        reported = _num(cells.get(amount_col, {}).get("value"))
        if reported is None:
            continue
        citation = f"{file} | {sheet}!{amount_col}{row['row_num']}"
        authentic = get_evidence(conn, citation)
        values = {col: cell.get("value") for col, cell in cells.items()}
        if authentic.get("row") == values and _num(
                authentic.get("value", {}).get("value")) == reported:
            summary.append((reported, citation))
    if len(summary) != 1 or summary[0][0] != total:
        return Answer(
            "The selected-base subtotal could not be reconciled to one "
            "original reported subtotal cell. No aggregate is asserted.",
            [], trace, verification_status="unverified")
    subtotal_citation = summary[0][1]
    sources = [*detail_citations, subtotal_citation]
    answer = (f"The selected base subtotal is {currency} {total:,.0f}. "
              f"Reconciled {len(detail_citations)} original priced rows to "
              f"the reported subtotal. Source: {subtotal_citation}. "
              "Other worksheets, including change orders, are excluded.")
    return Answer(answer, sources, trace,
                  verification_status="deterministically_verified",
                  structured={"currency": currency, "subtotal": str(total),
                              "sheet": sheet, "line_count": len(detail_citations)})


def original_contract_subtotal_comparison(
        conn: sqlite3.Connection, question: str, plan: QueryPlan):
    """Compare two authenticated operands, never infer missing contract values."""
    if (plan.scope_kind == "mixed"
            or not re.search(r"(?i)\b(?:equal|same)\b", question)
            or not re.search(r"(?i)\boriginal\b", question)
            or not re.search(r"(?i)\bcontract\b", question)
            or not re.search(r"(?i)\bbase\b", question)
            or not re.search(r"(?i)\bsubtotal\b", question)
            or re.search(r"(?i)\b(?:revised|amended|post[- ]change)\b", question)):
        return None
    from .agent import Answer

    local = verified_base_subtotal(conn, "What is the base subtotal?", plan)
    if local is None:
        return None
    trace = _trace("host_original_contract_comparison")
    if local.verification_status != "deterministically_verified":
        return Answer(
            "The base subtotal could not be independently reconciled. No "
            "contract-price comparison is asserted.", [], trace,
            verification_status="unverified")
    base = Decimal(local.structured["subtotal"])
    currency = local.structured["currency"]
    original = re.compile(
        r"(?i)\boriginal\b[^.!?\n]{0,70}?\bcontract\s+"
        r"(?:price|sum|amount|value)\b[^.!?\n]{0,35}?"
        r"\b(SAR|AED|USD|EUR|GBP)\s*([\d,]+(?:\.\d+)?)")
    candidates = []
    for row in conn.execute(
        "SELECT d.path,p.page,p.chunk,p.text FROM passages p "
        "JOIN documents d ON d.id=p.document_id "
        "WHERE d.status='ready' AND d.kind='pdf' ORDER BY d.path,p.page,p.chunk"
    ):
        if not re.search(r"(?i)contract", row["path"]):
            continue
        if re.search(r"(?i)\b(?:change[-_ ]order|draft|proposal|pending)\b",
                     row["path"].replace("_", " ")):
            continue
        source = f"{row['path']} | page {row['page']} | chunk {row['chunk']}"
        if get_evidence(conn, source).get("text") != row["text"]:
            continue
        for match in original.finditer(row["text"]):
            amount = _num(match.group(2))
            if amount is not None and amount.is_finite():
                candidates.append((match.group(1).upper(), amount, source))
    distinct = {(c, value) for c, value, _ in candidates}
    if len(distinct) != 1:
        return Answer(
            "The original contract amount is not uniquely established in "
            "the indexed signed contract passages. No comparison is inferred.",
            local.sources, trace, verification_status="unverified")
    contract_currency, signed = next(iter(distinct))
    sources = list(dict.fromkeys([*local.sources, *(c[2] for c in candidates)]))
    if contract_currency != currency:
        return Answer(
            f"Cannot directly compare {currency} base subtotal with "
            f"{contract_currency} signed contract price without a conversion basis.",
            sources, trace, verification_status="unverified")
    equal = signed == base
    return Answer(
        f"{'Yes' if equal else 'No'}. The selected base subtotal is "
        f"{currency} {base:,.0f}, while the original signed contract price "
        f"is {currency} {signed:,.0f}. Difference: "
        f"{currency} {abs(signed - base):,.0f}. "
        "The subtotal covers the selected worksheet only, not the entire contract.",
        sources, trace, verification_status="deterministically_verified",
        structured={"base_subtotal": str(base), "original_contract": str(signed),
                    "difference": str(abs(signed - base)), "currency": currency})


def complete_milestone_schedule(conn: sqlite3.Connection, question: str,
                                plan: QueryPlan):
    """Separate complete unique register rows by their *recorded* status only."""
    if (plan.scope_kind == "mixed"
            or not re.search(r"(?i)\b(?:schedule|milestones?|dates?)\b", question)
            or not re.search(r"(?i)\bcontractual\b", question)
            or not re.search(r"(?i)\bplanning\b", question)
            or not re.search(r"(?i)\bproposals?\b", question)
            or not re.search(r"(?i)\b(?:separate|classify|group|list|every|all)\b",
                             question)):
        return None

    from .agent import Answer

    sources = []
    candidates = []
    sheets: dict[tuple[str, str], list] = {}
    for row in conn.execute(
        "SELECT d.path,s.sheet,s.row_num,s.cells_json FROM sheet_rows s "
        "JOIN documents d ON d.id=s.document_id "
        "WHERE d.status='ready' ORDER BY d.path,s.sheet,s.row_num"):
        if plan.document_scope and row["path"] not in plan.document_scope:
            continue
        sheets.setdefault((row["path"], row["sheet"]), []).append(row)
    for (file, sheet), rows in sheets.items():
        headers = None
        header_at = None
        for row in rows:
            cell_values = {col: str(c.get("value") or "").strip().casefold()
                           for col, c in json.loads(row["cells_json"]).items()}
            names = {}
            for col, value in cell_values.items():
                if value in {"milestone", "milestone id", "milestone ref"}:
                    names["id"] = col
                elif value in {"date", "due date", "target date"}:
                    names["date"] = col
                elif value in {"classification", "category"}:
                    names["class"] = col
                elif value in {"approval", "approval status"}:
                    names["approval"] = col
                elif value in {"deliverable", "description"}:
                    names["description"] = col
            if {"id", "date", "class", "approval"} <= names.keys():
                headers, header_at = names, row["row_num"]
                break
        if headers is None:
            continue
        group = []
        for row in rows:
            if row["row_num"] <= header_at:
                continue
            values = {col: c.get("value")
                      for col, c in json.loads(row["cells_json"]).items()}
            identifier = str(values.get(headers["id"]) or "").strip()
            if not identifier and not any(str(value or "").strip()
                                          for value in values.values()):
                continue
            raw_date = values.get(headers["date"])
            status = str(values.get(headers["class"]) or "").strip().casefold()
            approval = str(values.get(headers["approval"]) or "").strip()
            if (not re.fullmatch(r"[A-Za-z]{1,8}-\d+", identifier)
                    or status not in {"contractual", "planning", "proposal"}
                    or not isinstance(raw_date, str)
                    or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_date)):
                return Answer(
                    "A schedule row has an unsupported identifier, date or "
                    "status. A complete classification cannot be guaranteed.",
                    [], _trace("host_complete_schedule"),
                    verification_status="unverified")
            try:
                iso = date.fromisoformat(raw_date).isoformat()
            except ValueError:
                return Answer("The register contains an invalid calendar date.",
                              [], _trace("host_complete_schedule"),
                              verification_status="unverified")
            citation = f"{file} | {sheet} | row {row['row_num']}"
            if get_evidence(conn, citation).get("row") != values:
                return Answer("The schedule row failed original-source verification.",
                              [], _trace("host_complete_schedule"),
                              verification_status="unverified")
            group.append({
                "id": identifier, "date": iso, "status": status,
                "approval": approval, "description": str(
                    values.get(headers.get("description", "")) or "").strip(),
                "citation": citation,
            })
        if group:
            candidates.append(group)
    if len(candidates) != 1:
        return None
    entries = candidates[0]
    keys = [row["id"].casefold() for row in entries]
    if len(keys) != len(set(keys)):
        return Answer("Duplicate milestone identifiers prevent a complete "
                      "unambiguous schedule report.", [],
                      _trace("host_complete_schedule"),
                      verification_status="unverified")
    by_type = {name: [row for row in entries if row["status"] == name]
               for name in ("contractual", "planning", "proposal")}
    lines = ["According to the complete indexed milestone register:"]
    for group in ("contractual", "planning", "proposal"):
        lines.append(f"{group.capitalize()} entries:")
        for row in by_type[group]:
            lines.append(
                f"- {row['id']}: {row['description']} — {row['date']}; "
                f"approval field: {row['approval'] or 'not recorded'} — "
                f"{row['citation']}")
            sources.append(row["citation"])
    lines.append("These are recorded classifications, not independent "
                 "proof of signed contract amendments.")
    return Answer(
        "\n".join(lines), sources,
        _trace("host_complete_schedule", entries=len(entries)),
        verification_status="deterministically_verified",
        structured={"milestones": entries})
