from __future__ import annotations

import re

from jobscraper.normalize.text import fold

_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("lead", re.compile(r"\b(lead|leader|principal|staff|head of|chief|cto|team ?lead|tech ?lead|teamleiter\w*|leiter\w*|responsable|chef d)\b")),
    ("senior", re.compile(r"\b(senior|sr|expert|experte|experienced|erfahren\w*|confirme\w*)\b")),
    ("junior", re.compile(r"\b(junior|jr|entry[- ]level|graduate|berufseinsteiger\w*|einsteiger\w*|debutant\w*|absolvent\w*|trainee)\b")),
    ("mid", re.compile(r"\b(mid|medior|intermediate|regular|professional)\b")),
]

_HINTS = {
    "lead": "lead", "principal": "lead", "director": "lead", "manager": "lead",
    "senior": "senior", "expert": "senior",
    "regular": "mid", "mid": "mid", "mid-level": "mid", "intermediate": "mid", "mid_level": "mid",
    "junior": "junior", "entry": "junior", "entry_level": "junior", "entry-level": "junior", "intern": "junior",
}


def seniority(title: str, hint: str | None = None) -> str:
    """junior | mid | senior | lead | unknown. A structured source hint wins."""
    if hint:
        key = fold(str(hint)).strip()
        if key in _HINTS:
            return _HINTS[key]
    folded = fold(title)
    for level, pattern in _RULES:
        if pattern.search(folded):
            return level
    return "unknown"
