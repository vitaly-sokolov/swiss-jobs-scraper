"""jobs.ch and jobup.ch — JobCloud public search API.

List:   GET /api/v1/public/search?category-ids[]=<id>&rows=20&page=<n>   (rows max 20)
Detail: GET /api/v1/public/search/job/<uuid>   (``template_text`` holds the ad HTML)

The listing carries a short ``preview`` only; the full ad is fetched in
``enrich`` for jobs that pass the filter and have not been enriched yet.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from html import escape
from typing import Any

from jobscraper.adapters.base import FetchContext, RawListing, parse_dt

PAGE_SIZE = 20

# /api/v1/public/meta/employment-types
EMPLOYMENT_TYPES = {
    "1": "Temporär",
    "2": "Freelance",
    "3": "Praktikum",
    "4": "Nebenerwerb",
    "5": "Festanstellung",
    "6": "Lehrstelle",
}


class JobCloudAdapter:
    name: str
    base_url: str
    fetch_method = "api"
    default_categories: list[int]
    link_lang: str = "en"

    def fetch(self, ctx: FetchContext) -> Iterator[RawListing]:
        categories = ctx.options.get("category_ids", self.default_categories)
        max_pages = int(ctx.options.get("max_pages", 500))
        page, num_pages = 1, 1
        while page <= min(num_pages, max_pages):
            params: list[tuple[str, Any]] = [("rows", PAGE_SIZE), ("page", page)]
            params += [("category-ids[]", c) for c in categories]
            data = ctx.http.get_json(f"{self.base_url}/api/v1/public/search", params=params)
            num_pages = int(data.get("num_pages") or 0)
            for doc in data.get("documents", []):
                try:
                    yield self.parse(doc)
                except Exception as exc:  # noqa: BLE001
                    ctx.item_error(self.name, str(doc.get("job_id")), exc)
            page += 1

    def parse(self, doc: dict[str, Any]) -> RawListing:
        job_id = doc["job_id"]
        links = doc.get("_links") or {}
        link = (links.get(f"detail_{self.link_lang}") or next(iter(links.values()), {})).get("href")
        return RawListing(
            source=self.name,
            source_job_id=job_id,
            url=link or f"{self.base_url}/{self.link_lang}/jobs/detail/{job_id}/",
            title=doc["title"].strip(),
            company=doc.get("company_name") if doc.get("company_visible", True) else None,
            location_text=doc.get("place"),
            description_html=_preview_html(doc.get("preview")),
            posted_at=parse_dt(doc.get("initial_publication_date") or doc.get("publication_date")),
            salary_text=_salary_text(doc.get("salary")),
            employment_text=_employment_text(doc),
            extra={
                "xref": job_id,
                "categories": [c.get("path") for c in doc.get("categories", [])],
                "employment_grades": doc.get("employment_grades") or [],
                "language_skills": doc.get("language_skills") or [],
                "country": "CH",
                "enriched": False,
            },
        )

    def enrich(self, ctx: FetchContext, listing: RawListing) -> RawListing:
        detail = ctx.http.get_json(f"{self.base_url}/api/v1/public/search/job/{listing.source_job_id}")
        location = listing.location_text
        if detail.get("zipcode") and detail.get("place"):
            location = f"{detail['zipcode']} {detail['place']}"
        return replace(
            listing,
            description_html=detail.get("template_text") or listing.description_html,
            location_text=location,
            salary_text=_salary_text(detail.get("salary")) or listing.salary_text,
            extra={
                **listing.extra,
                "enriched": True,
                "skills": detail.get("skills") or [],
                "application_url": detail.get("application_url") or detail.get("external_url") or None,
                "publication_end_date": detail.get("publication_end_date"),
            },
        )


def _preview_html(preview: str | None) -> str | None:
    if not preview:
        return None
    return "<p>" + escape(preview).replace("\n", "<br>") + "</p>"


def _employment_text(doc: dict[str, Any]) -> str | None:
    parts = [EMPLOYMENT_TYPES.get(str(t), "") for t in doc.get("employment_type_ids") or []]
    grades = doc.get("employment_grades") or []
    if grades:
        lo, hi = min(grades), max(grades)
        parts.append(f"{lo}%" if lo == hi else f"{lo}-{hi}%")
    text = ", ".join(p for p in parts if p)
    return text or None


def _salary_text(salary: Any) -> str | None:
    """JobCloud returns ``salary`` as null or ``{range: {minValue, maxValue}, unit, currency}``."""
    if not salary or not isinstance(salary, dict):
        return None
    rng = salary.get("range") or salary
    lo, hi = rng.get("minValue") or rng.get("min"), rng.get("maxValue") or rng.get("max")
    if not lo and not hi:
        return None
    currency = salary.get("currency") or "CHF"
    unit = {"YEAR": "year", "MONTH": "month", "HOUR": "hour", "DAY": "day"}.get(
        str(salary.get("unit") or "YEAR").upper(), "year"
    )
    amount = f"{lo} - {hi}" if lo and hi and lo != hi else f"{lo or hi}"
    return f"{currency} {amount} per {unit}"


class JobsChAdapter(JobCloudAdapter):
    name = "jobs_ch"
    base_url = "https://www.jobs.ch"
    default_categories = [106]  # information-technology-telecom
    link_lang = "en"


class JobupAdapter(JobCloudAdapter):
    name = "jobup"
    base_url = "https://www.jobup.ch"
    default_categories = [702]  # it-telecommunications
    link_lang = "fr"
