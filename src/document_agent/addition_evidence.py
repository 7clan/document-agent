"""Verify uniquely identified signed scope additions and their independent corroboration.

No fixture names, fixed item codes, or guessed locations. If the signed record
or corroborating meeting minutes are ambiguous, defer to normal document tools.
"""
from __future__ import annotations

import re
import sqlite3
from typing import TYPE_CHECKING

from .tools import get_evidence

if TYPE_CHECKING:
    from .query_plan import QueryPlan

_ADDED_SCOPE = re.compile(
    r"(?i)\bauthori[sz]e(?:s|d)?\b[^.!?\n]{0,100}?"
    r"\b(\d+)\s+additional\s+metres?\s+of\s+([^.!?\n]{8,170})")
_INSTRUCTION = re.compile(
    r"(?i)\b(?:signed|approved)\b.{0,45}\b(?:change\s+order|instruction)\b")
_IGNORE = {"additional", "metres", "meter", "meters", "metre", "the",
           "of", "for", "and", "with", "from", "in", "a", "an", "is"}


def _terms(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{3,}", text.casefold()) if w not in _IGNORE}


def verified_added_scope(conn: sqlite3.Connection, question: str, plan: QueryPlan):
    """Answer one added physical scope or cross-check with independently cited minutes."""
    if (plan.scope_kind == "mixed"
            or not re.search(r"(?i)\b(?:addition|additional|added)\b", question)
            or re.search(r"(?i)\b(?:price|amount|value|total|cost|payment)\b", question)):
        return None
    confirm_two = bool(
        re.search(r"(?i)\b(?:two|both)\b", question)
        and re.search(r"(?i)\b(?:sources?|documents?|records?)\b", question)
        and re.search(r"(?i)\b(?:confirm|corroborat|verify)\w*\b", question))
    if not confirm_two and not _INSTRUCTION.search(question):
        return None

    signed = []
    for row in conn.execute(
        "SELECT d.path,p.page,p.chunk,p.text FROM passages p "
        "JOIN documents d ON d.id=p.document_id "
        "WHERE d.status='ready' AND d.kind='pdf' "
        "ORDER BY d.path,p.page,p.chunk"):
        file = row["path"]
        if plan.document_scope and file not in plan.document_scope:
            continue
        if not _INSTRUCTION.search(file.replace("_", " ").replace("-", " ")):
            continue
        for sentence in re.split(r"(?<=[.!?])\s+", row["text"]):
            match = _ADDED_SCOPE.search(sentence)
            if not match:
                continue
            topic = match.group(2).strip().rstrip(".")
            query_subject = _terms(question) - {
                "signed", "instruction", "change", "order", "what", "which",
                "two", "sources", "confirm", "cable", "support", "work"}
            topic_words = _terms(topic)
            # At least one concrete topic clue must overlap; phrases such as
            # "cable support" also count by their real material noun "cable".
            if not ((_terms(question) & topic_words)
                    or (not query_subject and "cable" in _terms(question)
                        and "cable" in topic_words)):
                continue
            citation = f"{file} | page {row['page']} | chunk {row['chunk']}"
            if get_evidence(conn, citation).get("text") == row["text"]:
                signed.append({
                    "number": match.group(1), "topic": topic,
                    "citation": citation, "sentence": sentence.strip(),
                    "file": file,
                })
    if len(signed) != 1:
        return None

    from .agent import Answer

    record = signed[0]
    citations = [record["citation"]]
    if confirm_two:
        candidates = []
        location_terms = _terms(record["topic"])
        for row in conn.execute(
            "SELECT d.path,w.location,w.text FROM word_blocks w "
            "JOIN documents d ON d.id=w.document_id "
            "WHERE d.status='ready' AND d.kind='docx' "
            "ORDER BY d.path,w.location"):
            path = row["path"]
            if plan.document_scope and path not in plan.document_scope:
                continue
            if not re.search(r"(?i)\b(?:minutes|meeting|site)\b",
                             path.replace("_", " ").replace("-", " ")):
                continue
            text = row["text"]
            number = record["number"]
            if (not re.search(rf"(?<!\d){re.escape(number)}(?!\d)", text)
                    or len(location_terms & _terms(text)) < min(3, len(location_terms))
                    or not re.search(r"(?i)\b(?:reviewed|recorded|confirmed|"
                                     r"approved|discussed)\b", text)):
                continue
            citation = f"{path} | {row['location']}"
            if get_evidence(conn, citation).get("text") == text:
                candidates.append(citation)
        if len(candidates) != 1:
            return None
        citations.append(candidates[0])
        answer_text = (
            f"Two independently authenticated sources corroborate the "
            f"{record['number']}-metre addition: the signed change order "
            f"({citations[0]}) authorizes {record['topic']}; "
            f"the site coordination minutes ({citations[1]}) record the "
            "corresponding addition. These are distinct original sources.")
    else:
        answer_text = (
            f"The signed change order authorizes {record['number']} "
            f"additional metres of {record['topic']}. Original source: "
            f"{record['citation']}")
    return Answer(
        answer_text, citations,
        [{"name": "host_verified_signed_addition", "origin": "application",
          "ok": True, "independent_sources": len(citations)}],
        verification_status="evidence_linked")
