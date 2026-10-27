"""ictcareer.ch — JobCloud IT board (Next.js, server-rendered).

List:   GET /jobs?tag=<id>&tag=<id>&page=<n>  → ``__NEXT_DATA__`` …public.jobs.jobs (10 per page)
Detail: GET /job/<jobId>                      → ``__NEXT_DATA__`` …public.jobs.job

Each listing carries ``jcJobId``, the jobs.ch UUID of the same ad. It becomes
``xref`` so duplicates with jobs.ch are flagged reliably (D8).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from typing import Any

from jobscraper.adapters.base import FetchContext, RawListing, next_data, parse_dt

# 538 Software Engineering / Programmierung, 533 Datenbanken, 540 Webdesign / -programmierung
DEFAULT_TAGS = [538, 533, 540]


def _jobs_state(html: str) -> dict[str, Any]:
    return next_data(html)["props"]["pageProps"]["initialState"]["public"]["jobs"]


class IctCareerAdapter:
    name = "ictcareer"
    base_url = "https://www.ictcareer.ch"
    fetch_method = "http"

    def fetch(self, ctx: FetchContext) -> Iterator[RawListing]:
        tags = ctx.options.get("tags", DEFAULT_TAGS)
        max_pages = int(ctx.options.get("max_pages", 200))
        page = 1
        while page <= max_pages:
            params = [("tag", t) for t in tags] + [("page", page)]
            state = _jobs_state(ctx.http.get_text(f"{self.base_url}/jobs", params=params))["jobs"]
            jobs = state.get("jobs") or []
            if not jobs:
                break
            for job in jobs:
                try:
                    yield self.parse(job)
                except Exception as exc:  # noqa: BLE001
                    ctx.item_error(self.name, str(job.get("jobId")), exc)
            page_size = int(state.get("pageSize") or len(jobs))
            if page * page_size >= int(state.get("resultCount") or 0):
                break
            page += 1

    def parse(self, job: dict[str, Any]) -> RawListing:
        job_id = str(job["jobId"])
        return RawListing(
            source=self.name,
            source_job_id=job_id,
            url=f"{self.base_url}/job/{job_id}",
            title=job["title"].strip(),
            company=job.get("companyName"),
            location_text=job.get("location"),
            description_html=job.get("description") or job.get("summary"),
            posted_at=parse_dt(job.get("datePosted")),
            salary_text=None,
            employment_text=job.get("workload"),
            extra={"xref": job.get("jcJobId"), "country": "CH", "enriched": False},
        )

    def enrich(self, ctx: FetchContext, listing: RawListing) -> RawListing:
        job = _jobs_state(ctx.http.get_text(listing.url))["job"]
        employment = [
            entry.get("value")
            for tag in job.get("tags") or []
            for entry in tag.get("entries") or []
            if entry.get("value")
        ]
        employment_text = ", ".join(filter(None, [*employment, job.get("workload")])) or listing.employment_text
        return replace(
            listing,
            description_html=job.get("description") or listing.description_html,
            employment_text=employment_text,
            extra={**listing.extra, "enriched": True, "application_url": job.get("applyUrl")},
        )
