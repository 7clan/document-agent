"""Fast, non-blocking citation discovery for the original answer engine.

This is a provenance finder, NOT a factual verifier. It never calls an LLM,
rewrites a claim, changes a model decision, or suppresses an answer. Only
citation strings originating from indexed records can be returned.
"""
from __future__ import annotations

import re
import sqlite3
from collections import Counter
from collections.abc import Iterable
from typing import Any

from .hybrid import source_records

_STOP = frozenset({
    "the", "and", "for", "from", "which", "where", "what", "when", "with",
    "that", "this", "these", "those", "were", "was", "are", "have", "has",
    "had", "will", "would", "should", "could", "into", "after", "before",
    "about", "according", "based", "using", "does", "did", "doesn",
    "each", "every", "both", "their", "there", "then", "than", "only",
    "must", "please", "state", "give", "list", "identify", "specify",
    "tell", "show", "compare", "calculate", "exact", "which", "three",
})
_NEGATION = re.compile(
    r"\b(?:not|never|no|excluded|excluding|unsigned|unauthorized|unapproved"
    r"|pending|rejected|without)\b", re.IGNORECASE,
)
_ID = re.compile(r"\b[a-z]{1,6}[-–][0-9]{1,6}[a-z]?\b", re.IGNORECASE)
_NUMBER = re.compile(r"(?<![a-z\d])\d[\d,]*(?:\.\d+)?(?![a-z\d])", re.IGNORECASE)


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.casefold())


def _content_terms(text: str) -> set[str]:
    return {word for word in _words(text) if
            (len(word) >= 4 or word.isdigit()) and word not in _STOP}


def _numeric_anchors(text: str) -> set[str]:
    return {match.group().replace(",", "") for match in _NUMBER.finditer(text)}


def indexed_records(conn: sqlite3.Connection, *, limit: int = 3000
                    ) -> list[dict[str, Any]]:
    """Bound local I/O. Never download embeddings or call the answer provider."""
    records: list[dict[str, Any]] = []
    for item in source_records(conn):
        if len(records) >= limit:
            break
        citation = item.get("citation")
        original = item.get("text")
        if (isinstance(citation, str) and isinstance(original, str)
                and original.strip() and not citation.endswith(" | document")):
            records.append({"citation": citation, "text": original})
    return records


def _literal_support(claim: str, source: str) -> bool:
    """Conservatively locate a shared original phrase, never judge semantics.

    This is deliberately stricter than ordinary relevance scoring: a citation
    is attached directly only when there is a long, contiguous lexical overlap
    and *all* explicit numbers and IDs also occur in the same source.
    Derived calculations are left unverified and receive source suggestions.
    """
    claim_words = _words(claim)
    source_words = _words(source)
    if len(claim_words) < 5 or len(source_words) < 5:
        return False
    source_ids = {m.group().casefold().replace("–", "-") for m in _ID.finditer(source)}
    claim_ids = {m.group().casefold().replace("–", "-") for m in _ID.finditer(claim)}
    if not claim_ids.issubset(source_ids):
        return False
    if not _numeric_anchors(claim).issubset(_numeric_anchors(source)):
        return False
    if bool(_NEGATION.search(claim)) != bool(_NEGATION.search(source)):
        return False
    meaningful = _content_terms(claim)
    if len(meaningful) < 3:
        return False
    if len(meaningful & _content_terms(source)) < 3:
        return False
    # Requiring five consecutive words makes unrelated shared nouns insufficient.
    tokens = set(tuple(source_words[i:i + 5]) for i in
                 range(len(source_words) - 4))
    return any(tuple(claim_words[i:i + 5]) in tokens for i in
               range(len(claim_words) - 4))


def recover_literal_source(claim: str, records: Iterable[dict[str, Any]],
                           *, limit: int = 2) -> list[str]:
    """Return genuine indexed locations with substantial literal overlap."""
    found: list[str] = []
    for record in records:
        if _literal_support(claim, record["text"]):
            found.append(record["citation"])
            if len(found) >= limit:
                break
    return found


def related_source_locations(question: str, claims: Iterable[str],
                             records: Iterable[dict[str, Any]],
                             existing: Iterable[str] = (),
                             *, limit: int = 8) -> list[str]:
    """Rank useful extra file/page/row pointers without claiming proof.

    Prefer distinct documents not already represented. This is intentionally
    *not* an entailment decision or a new requirement for a successful answer.
    """
    question_terms = _content_terms(question)
    claim_terms = _content_terms(" ".join(claims))
    if not question_terms and not claim_terms:
        return []
    existing_set = set(existing)
    seen_docs = {cite.split(" | ")[0] for cite in existing_set}
    scored: list[tuple[float, str]] = []
    for record in records:
        citation = record["citation"]
        if citation in existing_set:
            continue
        words = _content_terms(record["text"])
        question_hits = len(question_terms & words)
        claim_hits = len(claim_terms & words)
        # No source is suggested merely because it contains common terms.
        if question_hits + claim_hits < 3 or (question_hits == 0 and claim_hits < 2):
            continue
        doc = citation.split(" | ")[0]
        name_hits = len(question_terms & _content_terms(doc))
        score = (question_hits * 2 + claim_hits * 2.3
                 + min(name_hits, 3) * 1.2
                 + (0.6 if doc not in seen_docs else 0))
        scored.append((score, citation))
    scored.sort(key=lambda item: (-item[0], item[1]))
    # A broad multi-file question benefits from different original documents.
    results: list[str] = []
    first_pass_docs: set[str] = set()
    for _, citation in scored:
        doc = citation.split(" | ")[0]
        if doc in seen_docs or doc in first_pass_docs:
            continue
        results.append(citation)
        first_pass_docs.add(doc)
        if len(results) >= limit:
            return results
    for _, citation in scored:
        if citation not in results:
            results.append(citation)
            if len(results) >= limit:
                break
    return results


def citation_assist(question: str, claims: list[str], conn: sqlite3.Connection,
                    existing: list[str], *, max_locations: int = 8
                    ) -> tuple[list[dict[str, Any]], list[str]]:
    """Return local records plus unverified related locations; never modify answers."""
    records = indexed_records(conn)
    candidates = related_source_locations(
        question, claims, records, existing, limit=max_locations,
    )
    return records, candidates
