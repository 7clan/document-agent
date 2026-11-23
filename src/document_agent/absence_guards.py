"""Conservative indexed-source checks for narrowly specified missing fields.

Never prove absence from unreadable files. This only reports what a bounded
scan of the *readable* index could not locate. Relevant positive evidence
disables this guard and leaves interpretation to the evidence-backed agent.
"""
from __future__ import annotations

import re
import sqlite3
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .query_plan import QueryPlan

_PHONE_REQUEST = re.compile(r"(?i)\b(?:phone|telephone|mobile|contact\s+number)\b")
_PAYMENT_REQUEST = re.compile(
    r"(?i)\b(?:installments?|instalments?|payment[s]?|billing)\b")
_PAYMENT_TIMETABLE_REQUEST = re.compile(
    r"(?i)\b(?:timetable|schedule|installments?|instalments?|stages?)\b")
_PHONE_EVIDENCE = re.compile(
    r"(?i)\b(?:telephone|phone|mobile|whatsapp|fax|tel\.?|direct\s+line)\b")
_PAYMENT_EVIDENCE = re.compile(
    r"(?i)\b(?:installments?|instalments?|payment|invoice|billing|"
    r"progress\s+claims?|retention\s+release|stage\s+payments?)\b")


def scoped_absence_answer(conn: sqlite3.Connection, question: str,
                          plan: QueryPlan):
    """State *not found in indexed readable documents*, never global absence."""
    if plan.scope_kind == "mixed":
        return None
    if _PHONE_REQUEST.search(question):
        field = "requested phone/contact number"
        evidence_pattern = _PHONE_EVIDENCE
    elif (_PAYMENT_REQUEST.search(question)
          and _PAYMENT_TIMETABLE_REQUEST.search(question)):
        field = "contractual installment-payment timetable"
        evidence_pattern = _PAYMENT_EVIDENCE
    else:
        return None

    selected = set(plan.document_scope)
    # Each readable document must have some structured content, otherwise
    # the absence determination cannot be more informative than the agent.
    docs = conn.execute(
        "SELECT id,path FROM documents WHERE status='ready' ORDER BY path"
    ).fetchall()
    docs = [doc for doc in docs if not selected or doc["path"] in selected]
    if not docs:
        return None
    checked: set[int] = set()
    inspected = 0
    for table, column in (
        ("passages", "text"),
        ("word_blocks", "text"),
        ("sheet_rows", "cells_json"),
    ):
        for row in conn.execute(
            f"SELECT t.document_id,t.{column} AS content FROM {table} t "
            "JOIN documents d ON d.id=t.document_id "
            "WHERE d.status='ready' ORDER BY d.path LIMIT 10001"
        ):
            if selected and row["document_id"] not in {d["id"] for d in docs}:
                continue
            inspected += 1
            if inspected > 10000:
                return None
            checked.add(row["document_id"])
            if evidence_pattern.search(str(row["content"] or "")):
                # A matching label can indicate a real value; let the
                # normal agent inspect and cite its original location.
                return None
    if len(checked) != len(docs):
        return None

    failed = conn.execute(
        "SELECT COUNT(*) FROM documents WHERE status!='ready'"
    ).fetchone()[0]
    if selected:
        failed = 0
    from .agent import Answer

    sentence = (
        f"No {field} was found in the indexed readable documents checked "
        f"({len(docs)} file(s)).")
    if failed:
        sentence += (
            f" {failed} additional file(s) were unreadable or failed indexing; "
            "this does not establish absence from those files.")
    return Answer(
        sentence, [],
        [{"name": "host_scoped_missing_field", "origin": "application",
          "ok": True, "documents_checked": len(docs),
          "unreadable_count": failed, "text_records_checked": inspected}],
        verification_status="unverified")
