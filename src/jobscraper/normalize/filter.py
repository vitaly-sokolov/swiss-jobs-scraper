"""Tech filter (§6.2) scoped to backend development and AI engineering (D16).

Order:
1. Source category filter: applied by each adapter's query (sources.yaml).
2. Allowlist: the title matches a backend/AI role pattern, **or** the title is a
   generic engineering role and the description names enough backend/AI terms.
3. Denylist on the title (sales, recruiting, support, frontend-only, …) unless an
   override pattern matches (e.g. "fullstack" beats "frontend").
Also applies the geography rule (D5): Swiss, border-region, or remote roles.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from jobscraper.normalize.text import fold


def _compile(patterns: list[str] | None) -> list[re.Pattern[str]]:
    return [re.compile(fold(p), re.I) for p in patterns or []]


@dataclass(frozen=True)
class Verdict:
    keep: bool
    reason: str


class TechFilter:
    def __init__(self, config: dict[str, Any]) -> None:
        self.title_allow = _compile(config.get("title_allow"))
        self.title_role = _compile(config.get("title_role"))
        self.description_terms = _compile(config.get("description_terms"))
        self.description_min_terms = int(config.get("description_min_terms", 2))
        self.title_deny = _compile(config.get("title_deny"))
        self.title_deny_unless = _compile(config.get("title_deny_unless"))
        self.company_deny = _compile(config.get("company_deny"))

    def check_title(self, title: str) -> Verdict | None:
        """Decide on the title alone; None means the description is needed."""
        t = fold(title)
        if any(p.search(t) for p in self.title_deny) and not any(p.search(t) for p in self.title_deny_unless):
            return Verdict(False, "title_deny")
        if any(p.search(t) for p in self.title_allow):
            return Verdict(True, "title_allow")
        if not any(p.search(t) for p in self.title_role):
            return Verdict(False, "no_role")
        return None

    def check(self, title: str, description_text: str = "", company: str | None = None, extra_terms: str = "") -> Verdict:
        if company and any(p.search(fold(company)) for p in self.company_deny):
            return Verdict(False, "company_deny")
        verdict = self.check_title(title)
        if verdict is not None:
            return verdict
        haystack = fold(f"{description_text}\n{extra_terms}")
        hits = sum(1 for p in self.description_terms if p.search(haystack))
        if hits >= self.description_min_terms:
            return Verdict(True, f"description_terms:{hits}")
        return Verdict(False, "too_few_terms")


ALLOWED_COUNTRIES = {"CH", "LI"}


def geography_ok(country: str | None, border: bool, remote: str) -> bool:
    """D5: Swiss roles, remote roles open to Switzerland, and border-region jobs."""
    if country is None or country in ALLOWED_COUNTRIES or border:
        return True
    return remote == "remote"
