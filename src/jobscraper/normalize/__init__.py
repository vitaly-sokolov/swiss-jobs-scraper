"""Map ``RawListing`` → ``NormalizedJob`` (§6.3)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from jobscraper.adapters.base import RawListing
from jobscraper.config import Vocab
from jobscraper.normalize.employment import employment_type
from jobscraper.normalize.filter import TechFilter, Verdict, geography_ok
from jobscraper.normalize.language import detect_language
from jobscraper.normalize.location import Locator, remote_mode
from jobscraper.normalize.salary import parse_salary
from jobscraper.normalize.seniority import seniority
from jobscraper.normalize.tags import Tagger
from jobscraper.normalize.text import fold, html_to_text, normalize_company, normalize_title


@dataclass
class NormalizedJob:
    source: str
    source_job_id: str
    url: str
    title: str
    company: str | None
    location_text: str | None
    canton: str | None
    country: str | None
    remote: str
    seniority: str
    employment_type: str
    salary_min: Decimal | None
    salary_max: Decimal | None
    salary_currency: str | None
    salary_period: str | None
    salary_text: str | None
    tech_tags: list[str]
    language: str | None
    description_html: str | None
    description_hash: str | None
    dedupe_key: str
    xref: str | None
    posted_at: datetime | None
    enriched: bool          # description is the full ad, not a listing preview
    details_fetched: bool   # detail page was fetched during this run
    raw: dict[str, Any] = field(default_factory=dict)


def dedupe_key(company: str | None, title: str, place: str | None) -> str:
    """sha256(company | normalized title | canton-or-city) — lowercase, accent-folded.

    When the canton is unknown the folded location text is used instead, so jobs
    from the same company in different unknown places are not merged by accident.
    """
    parts = [normalize_company(company), normalize_title(title), fold(place or "").strip()]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


class Normalizer:
    def __init__(self, vocab: Vocab) -> None:
        self.filter = TechFilter(vocab.tech_keywords)
        self.tagger = Tagger(vocab.tech_tags)
        self.locator = Locator(vocab.locations)

    def prefilter(self, raw: RawListing) -> Verdict:
        """Filter using only what the listing page carries (before detail fetch)."""
        return self.filter.check(
            raw.title,
            html_to_text(raw.description_html),
            raw.company,
            extra_terms=" ".join(_extra_terms(raw)),
        )

    def geography(self, raw: RawListing) -> bool:
        place = self.locator.locate(raw.location_text, raw.extra.get("country"))
        remote = remote_mode(raw.extra.get("remote") or raw.extra.get("workplace"), raw.title, raw.location_text)
        return geography_ok(place.country, place.border, remote)

    def normalize(self, raw: RawListing) -> NormalizedJob:
        text = html_to_text(raw.description_html)
        place = self.locator.locate(raw.location_text, raw.extra.get("country"))
        remote = remote_mode(
            raw.extra.get("remote") or raw.extra.get("workplace"),
            title=raw.title,
            location=raw.location_text,
            body=text[:5000],
        )
        salary = parse_salary(raw.salary_text)
        tags = self.tagger.tags(raw.title, text, provided=_extra_terms(raw))
        language = (
            _language_hint(raw.extra.get("language_code"))
            or detect_language(text or None)
            # No description (e.g. SwissDevJobs light feed): fall back to the
            # language the ad requires, which is almost always the ad's language.
            or _language_hint(_LANGUAGE_NAMES.get(str(raw.extra.get("language_required")).lower()))
        )
        description_hash = hashlib.sha256(text.encode()).hexdigest() if text else None
        city_or_canton = place.canton or raw.location_text
        return NormalizedJob(
            source=raw.source,
            source_job_id=raw.source_job_id,
            url=raw.url,
            title=raw.title,
            company=raw.company,
            location_text=raw.location_text,
            canton=place.canton,
            country=place.country,
            remote=remote,
            seniority=seniority(raw.title, raw.extra.get("seniority")),
            employment_type=employment_type(raw.employment_text, raw.title),
            salary_min=salary.min,
            salary_max=salary.max,
            salary_currency=salary.currency,
            salary_period=salary.period,
            salary_text=raw.salary_text,
            tech_tags=tags,
            language=language,
            description_html=raw.description_html,
            description_hash=description_hash,
            dedupe_key=dedupe_key(raw.company, raw.title, city_or_canton),
            xref=raw.extra.get("xref"),
            posted_at=raw.posted_at,
            enriched=bool(raw.extra.get("enriched", True)),
            details_fetched=raw.extra.get("enriched") is True,
            raw=_jsonable({"extra": raw.extra, "employment_text": raw.employment_text}),
        )


def _extra_terms(raw: RawListing) -> list[str]:
    terms: list[str] = []
    for key in ("technologies", "filter_tags", "skills", "topics"):
        value = raw.extra.get(key) or []
        terms += [str(v.get("name", "")) if isinstance(v, dict) else str(v) for v in value]
    return terms


_LANGUAGE_NAMES = {"german": "de", "deutsch": "de", "french": "fr", "francais": "fr", "english": "en"}


def _language_hint(code: str | None) -> str | None:
    if not code:
        return None
    code = code.lower()[:2]
    return code if code in ("de", "fr", "en") else "other"


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
