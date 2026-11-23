"""Evidence-linked read-only checks for an excluded optional package.

Three independent document roles must agree before stating a signed-paper
authorization decision: original signed scope, later signed instruction, and
pending decision. An unknown or conflicting role routes to the normal agent.
"""
from __future__ import annotations

import re
import sqlite3
from typing import TYPE_CHECKING

from .tools import get_evidence

if TYPE_CHECKING:
    from .query_plan import QueryPlan

_INTENT = re.compile(r"(?i)\b(?:order(?:ed)?|purchas\w*|procure\w*|authoriz\w*)\b")
_PACKAGE = re.compile(r"(?i)\b(?:optional|battery|energy|stor(?:e|age)|package)\b")
_SIGNED = re.compile(r"(?i)\b(?:signed|contract|approved)\b")
_TOPIC = re.compile(
    r"(?i)^(.{4,100}?)\s+is\s+an?\s+optional\s+future\s+package\b"
)
_STOP = {"phase", "future", "optional", "package", "the", "and", "with"}


def _words(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z]{3,}", value.casefold())
            if token not in _STOP}


def _matches_topic(topic: str, question: str) -> bool:
    # Energy store and battery storage are equivalent search expressions,
    # but no conclusion follows unless *all three signed-document roles*
    # themselves name the same single optional package.
    q = _words(question)
    t = _words(topic)
    if "energy" in q and ("store" in q or "storage" in q):
        q.update(("battery", "storage"))
    if "store" in q:
        q.add("storage")
    return bool(q & t)


def verified_optional_procurement(conn: sqlite3.Connection, question: str,
                                  plan: QueryPlan):
    """Return a documented *no* only when all original locations authenticate."""
    if (plan.scope_kind != "all_indexed" or not _INTENT.search(question)
            or not _PACKAGE.search(question) or not _SIGNED.search(question)):
        return None

    signed_scope = []
    signed_orders = []
    pending_requests = []
    for row in conn.execute(
        "SELECT d.path,p.page,p.chunk,p.text FROM passages p "
        "JOIN documents d ON d.id=p.document_id "
        "WHERE d.status='ready' AND d.kind='pdf' "
        "ORDER BY d.path,p.page,p.chunk"
    ):
        filename = row["path"].replace("_", " ").replace("-", " ").casefold()
        citation = f"{row['path']} | page {row['page']} | chunk {row['chunk']}"
        if get_evidence(conn, citation).get("text") != row["text"]:
            continue
        value = (row["text"], citation)
        if ("signed" in filename and "contract" in filename
                and "change order" not in filename):
            signed_scope.append(value)
        elif "signed" in filename and "change order" in filename:
            signed_orders.append(value)
        elif "pending" in filename and "change request" in filename:
            pending_requests.append(value)

    options = []
    for text, citation in signed_scope:
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            match = _TOPIC.fullmatch(sentence.strip().rstrip("."))
            if not match:
                # The sentence often appends ", not authorized procurement".
                match = _TOPIC.match(sentence.strip())
            if match is None:
                continue
            topic = match.group(1).strip()
            if not _matches_topic(topic, question):
                continue
            excluded = re.search(
                rf"(?i){re.escape(topic)}[^.!?\n]{{0,40}}\b(?:is|are)\s+excluded",
                text)
            unauthorized = re.search(
                rf"(?i){re.escape(topic)}\s+is\s+an?\s+optional\s+future\s+package"
                r"[^.!?\n]{0,65}\bnot\s+authori[sz]ed\b",
                text)
            if excluded and unauthorized:
                options.append((topic, citation))
    if len(options) != 1:
        return None

    topic, contract = options[0]
    keyword_terms = _words(topic)
    denials = []
    for text, citation in signed_orders:
        if re.search(
            rf"(?i)\bdoes\s+not\s+authori[sz]e\s+{re.escape(topic)}\b",
            text):
            denials.append(citation)
    pending = []
    for text, citation in pending_requests:
        overlap = _words(text) & keyword_terms
        phase = re.search(r"(?i)\bphase\s+(\d+)\b", topic)
        same_phase = bool(phase and re.search(
            rf"(?i)\bphase\s+{re.escape(phase.group(1))}\b", text))
        if ((len(overlap) >= min(2, len(keyword_terms))
             or (same_phase and len(overlap) >= 1))
                and re.search(r"(?i)\b(?:procurement|purchase|order)\b", text)
                and re.search(r"(?i)\b(?:remains\s+open|not\s+approved|pending)\b",
                              text)):
            pending.append(citation)
    if len(denials) != 1 or len(pending) != 1:
        return None

    # The meaning of the signed documents is deliberately confined to their
    # explicit clauses, without inferring that other/unknown documents are absent.
    from .agent import Answer

    sources = [contract, denials[0], pending[0]]
    return Answer(
        f"No. The original signed scope excludes {topic} and calls it an "
        f"optional package, not authorized procurement — {contract}. "
        f"The signed change order explicitly does not authorize {topic} — "
        f"{denials[0]}. The separate pending request for the related procurement "
        f"decision remains open — {pending[0]}. This is not authorization to "
        "place an order.",
        sources,
        [{"name": "host_optional_procurement_evidence",
          "origin": "application", "ok": True, "authenticated_source_count": 3}],
        verification_status="evidence_linked",
    )
