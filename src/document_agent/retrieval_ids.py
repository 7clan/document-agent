"""Recognize whole structured references so EL-103 never matches EL-1030."""
from __future__ import annotations

import re

# Require letters and a numeric suffix: ignore words like "follow-up".
REFERENCE_RE = re.compile(
    r"(?<![\w])[A-Za-z]{1,8}[-_]\d+(?:[-_][A-Za-z0-9]+)*(?![\w])",
    re.IGNORECASE,
)


def requested_references(query: str) -> list[str]:
    """Return explicitly requested IDs, deduplicated in first-seen order."""
    return list(dict.fromkeys(match.group().casefold() for match in REFERENCE_RE.finditer(query)))


def matches_reference(text: str, references: list[str]) -> bool:
    """If references were supplied, require at least one whole exact ID."""
    if not references:
        return True
    return any(
        re.search(r"(?<![\w])" + re.escape(ref) + r"(?![\w])", text, re.IGNORECASE)
        is not None
        for ref in references
    )
