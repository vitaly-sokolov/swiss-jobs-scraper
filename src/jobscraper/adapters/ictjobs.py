"""ictjobs.ch — WordPress site; job ads are posts.

List:   GET /wp-json/wp/v2/posts?ctx_prof_group=<ids>&per_page=100&page=<n>
        (``X-WP-TotalPages`` header; ``content`` is empty in the API)
Detail: the post's ``link`` page carries a schema.org ``JobPosting`` in JSON-LD
        with description, employer, address and employment type.

The board is small (~180 live ads), so details are fetched inline for every
listing in the selected profession groups.
"""

from __future__ import annotations

import html
from collections.abc import Iterator
from typing import Any

from jobscraper.adapters.base import FetchContext, RawListing, job_posting_ld, parse_dt

# ctx_prof_group: 3159 Software-Entwicklung / Data Management / Webdesign / UX/UI,
#                 3672 AI / Machine Learning / Robotik / Automatisierung
DEFAULT_PROF_GROUPS = [3159, 3672]

_FIELDS = "id,date_gmt,modified_gmt,link,title,ctx_employment_type,ctx_work_location"


class IctJobsAdapter:
    name = "ictjobs"
    base_url = "https://ictjobs.ch"
    fetch_method = "http"

    def fetch(self, ctx: FetchContext) -> Iterator[RawListing]:
        groups = ctx.options.get("prof_groups", DEFAULT_PROF_GROUPS)
        page, total_pages = 1, 1
        while page <= total_pages:
            response = ctx.http.get(
                f"{self.base_url}/wp-json/wp/v2/posts",
                params={
                    "ctx_prof_group": ",".join(map(str, groups)),
                    "per_page": 100,
                    "page": page,
                    "_fields": _FIELDS,
                },
            )
            total_pages = int(response.headers.get("X-WP-TotalPages", "1"))
            for post in response.json():
                try:
                    yield self.parse(post, ctx.http.get_text(post["link"]))
                except Exception as exc:  # noqa: BLE001
                    ctx.item_error(self.name, str(post.get("id")), exc)
            page += 1

    def parse(self, post: dict[str, Any], detail_html: str) -> RawListing:
        ld = job_posting_ld(detail_html) or {}
        title = html.unescape((post.get("title") or {}).get("rendered") or ld.get("title") or "").strip()
        if not title:
            raise ValueError("missing title")
        org = ld.get("hiringOrganization") or {}
        address = _address(ld.get("jobLocation"))
        employment = ld.get("employmentType")
        if isinstance(employment, list):
            employment = ", ".join(employment)
        return RawListing(
            source=self.name,
            source_job_id=str(post["id"]),
            url=post["link"],
            title=title,
            company=org.get("name") if isinstance(org, dict) else None,
            location_text=address.get("text"),
            description_html=_description_html(ld.get("description")),
            posted_at=parse_dt(ld.get("datePosted")) or parse_dt((post.get("date_gmt") or "") + "Z"),
            salary_text=_salary_text(ld.get("baseSalary")),
            employment_text=employment,
            extra={
                "country": address.get("country"),
                "region": address.get("region"),
                "remote": ld.get("jobLocationType"),
                "valid_through": ld.get("validThrough"),
            },
        )


def _address(location: Any) -> dict[str, str | None]:
    if isinstance(location, list):
        location = location[0] if location else None
    if not isinstance(location, dict):
        return {}
    addr = location.get("address") or {}
    if isinstance(addr, str):
        return {"text": addr}
    postal, city = addr.get("postalCode"), addr.get("addressLocality")
    text = " ".join(p for p in (postal, city) if p) or None
    country = addr.get("addressCountry")
    if isinstance(country, dict):
        country = country.get("name")
    return {"text": text, "region": addr.get("addressRegion"), "country": country}


def _description_html(description: str | None) -> str | None:
    if not description:
        return None
    if "<" in description:
        return description
    paragraphs = [html.escape(p.strip()) for p in description.split("\n") if p.strip()]
    return "".join(f"<p>{p}</p>" for p in paragraphs)


def _salary_text(base_salary: Any) -> str | None:
    if not isinstance(base_salary, dict):
        return None
    value = base_salary.get("value") or {}
    if not isinstance(value, dict):
        return None
    lo, hi = value.get("minValue"), value.get("maxValue")
    amount = value.get("value")
    if not (lo or hi or amount):
        return None
    unit = str(value.get("unitText") or "YEAR").lower()
    currency = base_salary.get("currency") or "CHF"
    span = f"{lo} - {hi}" if lo and hi else f"{lo or hi or amount}"
    return f"{currency} {span} per {unit}"
