"""Application-owned source records used for validation and bounded recovery."""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from .retrieval_ids import requested_references
from .tools import DATE_REGEX, _date_info, get_evidence


@dataclass(frozen=True)
class EvidenceRecord:
    source_id: str
    filename: str
    kind: str
    document_status: str
    index_error: str
    location: str
    text: str
    cells: dict[str, Any] | None
    amount: Decimal | None
    currency: str | None
    dates: tuple[str, ...]
    identifiers: tuple[str, ...]
    status_terms: tuple[str, ...]
    warnings: tuple[str, ...]

    def original(self) -> str:
        if self.cells is not None:
            return " | ".join(f"{column}: {value}" for column, value in self.cells.items()
                              if value is not None)
        return self.text


def record_for_citation(
    conn: sqlite3.Connection, citation: str,
    financial: dict[str, tuple[str, str]] | None = None,
) -> EvidenceRecord | None:
    """Resolve only exact indexed citations; never construct a substitute source."""
    filename, separator, location = citation.partition(" | ")
    if not separator:
        return None
    if location == "document":
        return None  # An inventory entry cannot substantiate a factual passage.
    row = conn.execute("SELECT kind,status,error FROM documents WHERE path=?", (filename,)).fetchone()
    if row is None:
        return None
    original = get_evidence(conn, citation)
    if "error" in original:
        return None
    cells = original.get("row") if isinstance(original.get("row"), dict) else None
    text = str(original.get("text", ""))
    value_text = " | ".join(str(value) for value in cells.values()) if cells else text
    normalized_dates = []
    for match in DATE_REGEX.finditer(value_text):
        normalized, ambiguous = _date_info(match.group())
        if normalized and not ambiguous:
            normalized_dates.append(normalized)
    status_terms = tuple(dict.fromkeys(match.group().casefold() for match in re.finditer(
        r"\b(?:not approved|unapproved|approved|contractual|binding|planning|"
        r"proposed|pending|rejected|excluded)\b", value_text, re.IGNORECASE)))
    amount = None
    currency = None
    if financial and citation in financial:
        amount_text, currency = financial[citation]
        try:
            amount = Decimal(amount_text)
        except InvalidOperation:
            amount = None
    warnings = []
    if row["error"]:
        warnings.append(str(row["error"]))
    if original.get("extraction_method") == "text_lines":
        warnings.append("Heuristic PDF text-line extraction; inspect the original page")
    return EvidenceRecord(
        source_id=citation, filename=filename, kind=row["kind"],
        document_status=row["status"], index_error=row["error"] or "",
        location=location, text=text, cells=cells, amount=amount,
        currency=currency, dates=tuple(dict.fromkeys(normalized_dates)),
        identifiers=tuple(requested_references(value_text)),
        status_terms=status_terms, warnings=tuple(warnings),
    )


def build_ledger(
    conn: sqlite3.Connection, citations: list[str],
    financial: dict[str, tuple[str, str]] | None = None,
) -> dict[str, EvidenceRecord]:
    """Deduplicate locations while retaining all facts inside each original record."""
    ledger: dict[str, EvidenceRecord] = {}
    for citation in citations:
        if citation in ledger:
            continue
        record = record_for_citation(conn, citation, financial)
        if record is not None:
            ledger[citation] = record
    return ledger
