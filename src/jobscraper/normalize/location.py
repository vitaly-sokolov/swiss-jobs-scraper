"""Canton, country and remote mode from free location text (§6.3, D5)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from jobscraper.normalize.text import fold

CANTONS = {
    "AG", "AI", "AR", "BE", "BL", "BS", "FR", "GE", "GL", "GR", "JU", "LU", "NE", "NW",
    "OW", "SG", "SH", "SO", "SZ", "TG", "TI", "UR", "VD", "VS", "ZG", "ZH",
}
_CANTON_CODE = re.compile(r"(?<![A-Za-z])(" + "|".join(sorted(CANTONS)) + r")(?![A-Za-z])")
_POSTCODE = re.compile(r"(?<!\d)(?:CH-)?(\d{4})(?!\d)")

_COUNTRY_ALIASES = {
    "ch": "CH", "che": "CH", "switzerland": "CH", "schweiz": "CH", "suisse": "CH", "svizzera": "CH",
    "li": "LI", "liechtenstein": "LI",
    "de": "DE", "deu": "DE", "germany": "DE", "deutschland": "DE", "allemagne": "DE",
    "fr": "FR", "fra": "FR", "france": "FR", "frankreich": "FR",
    "it": "IT", "ita": "IT", "italy": "IT", "italien": "IT", "italia": "IT", "italie": "IT",
    "at": "AT", "aut": "AT", "austria": "AT", "osterreich": "AT", "autriche": "AT",
}

REMOTE_MODES = ("onsite", "hybrid", "remote", "unknown")


def country_code(value: str | None) -> str | None:
    if not value:
        return None
    return _COUNTRY_ALIASES.get(fold(value).strip())


@dataclass(frozen=True)
class Place:
    canton: str | None
    country: str | None
    border: bool = False


class Locator:
    def __init__(self, config: dict[str, Any]) -> None:
        self._cities: list[tuple[re.Pattern[str], str]] = []
        for canton, names in (config.get("cantons") or {}).items():
            for name in names:
                self._cities.append((_word(name), canton))
        # Longest names first so "St. Gallen" wins over "Gallen", "Basel-Land" over "Basel".
        self._cities.sort(key=lambda item: -len(item[0].pattern))
        self._border: list[tuple[re.Pattern[str], str]] = []
        for country, names in (config.get("border_towns") or {}).items():
            for name in names:
                self._border.append((_word(name), country))
        self._postcodes: list[tuple[int, int, str]] = [
            (int(lo), int(hi), canton)
            for canton, ranges in (config.get("postcode_ranges") or {}).items()
            for lo, hi in ranges
        ]

    def locate(self, text: str | None, country_hint: str | None = None) -> Place:
        hint = country_code(country_hint) if country_hint and len(country_hint) > 2 else country_hint
        if not text:
            return Place(None, hint)
        folded = fold(text)
        for pattern, country in self._border:
            if pattern.search(folded):
                return Place(None, country, border=True)
        if hint and hint not in ("CH", None):
            return Place(None, hint)
        if match := _CANTON_CODE.search(text):
            return Place(match.group(1), "CH")
        for pattern, canton in self._cities:
            if pattern.search(folded):
                return Place(canton, "CH")
        for match in _POSTCODE.finditer(text):
            code = int(match.group(1))
            for lo, hi, canton in self._postcodes:
                if lo <= code <= hi:
                    return Place(canton, "CH")
        return Place(None, hint)


def _word(name: str) -> re.Pattern[str]:
    folded = re.escape(fold(name)).replace(r"\ ", r"[\s.-]*")
    return re.compile(rf"(?<![a-z]){folded}(?![a-z])")


_FULL_REMOTE = re.compile(
    r"\b(full[ -]?remote|fully remote|100\s*% remote|remote[- ]first|remote only|vollstandig remote|"
    r"komplett remote|100\s*% home[- ]?office|full[ -]time remote|teletravail (?:a )?100\s*%)",
)
_REMOTE_WORD = re.compile(
    r"\b(remote|home[- ]?office|work from home|wfh|telearbeit|mobiles arbeiten|teletravail|a distance)\b"
)
_HYBRID = re.compile(r"\b(hybrid\w*|teilweise remote|partially remote|teletravail partiel)\b")
_ONSITE = re.compile(r"\b(on[- ]?site|vor ort|sur site|office[- ]based|in the office|prasenz\w*)\b")


def remote_mode(hint: str | None, title: str | None = None, location: str | None = None, body: str | None = None) -> str:
    """onsite | hybrid | remote | unknown.

    Structured source hints win. "Remote" in the title or location means remote.
    In the ad body only explicit full-remote phrases count as remote; a plain
    home-office mention ("Homeoffice möglich") is treated as hybrid.
    """
    if hint:
        h = fold(hint)
        if "hybrid" in h:
            return "hybrid"
        if "remote" in h or "telecommute" in h:
            return "remote"
        if h in ("office", "onsite", "on-site", "on_site"):
            return "onsite"
    head = fold(" ".join(t for t in (title, location) if t))
    text = fold(body or "")
    if _FULL_REMOTE.search(head) or _FULL_REMOTE.search(text):
        return "remote"
    if _HYBRID.search(head) or _HYBRID.search(text):
        return "hybrid"
    if _REMOTE_WORD.search(head):
        return "remote"
    if _REMOTE_WORD.search(text):
        return "hybrid"
    if _ONSITE.search(head) or _ONSITE.search(text):
        return "onsite"
    return "unknown"
