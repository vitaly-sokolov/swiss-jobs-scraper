"""foorilla.com — official API (https://foorilla.com/api/v1/docs).

Phase 0 finding: every endpoint except the root needs an ``Api-Key`` header, and
keys require a paid PRO+ subscription. Without ``api_keys.foorilla`` in
config.yaml this adapter raises, so the run is ``failed`` with a clear message;
disable the source in sources.yaml until a key exists.

Data is CC BY-SA 4.0: notifications link back to the source posting.

Jobs:  GET /api/v1/hiring/job/?country=<id>&page=<n>&page_size=<k>
Geo:   GET /api/v1/core/geocountry/?name=Switzerland  → country id
Only published ``salary_min``/``salary_max`` are used, never ``*_est`` (D11).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

from jobscraper.adapters.base import FetchContext, RawListing, parse_dt

API = "https://foorilla.com/api/v1"
PAGE_SIZE = 200
# work_mode codes per /api/v1/core/metadata/ — verify once a key is available.
WORK_MODES = {1: "onsite", 2: "hybrid", 3: "remote"}


class MissingApiKey(RuntimeError):
    pass


class FoorillaAdapter:
    name = "foorilla"
    base_url = "https://foorilla.com"
    fetch_method = "api"

    def fetch(self, ctx: FetchContext) -> Iterator[RawListing]:
        key = ctx.settings.api_key(self.name)
        if not key:
            raise MissingApiKey("foorilla needs api_keys.foorilla in config.yaml (PRO+ subscription)")
        headers = {"Api-Key": key}
        country_id = ctx.options.get("country_id") or self._country_id(ctx, headers)
        params: dict[str, Any] = {"country": country_id, "page_size": PAGE_SIZE}
        if ctx.options.get("exclude_agencies"):
            params["company_agency"] = "false"
        if days := ctx.options.get("published_within_days"):
            params["published_after"] = (datetime.now(UTC) - timedelta(days=int(days))).date().isoformat()
        page, pages = 1, 1
        while page <= pages:
            data = ctx.http.get_json(f"{API}/hiring/job/", params={**params, "page": page}, headers=headers)
            pages = int(data.get("pages") or 0)
            for job in data.get("results", []):
                try:
                    if job.get("expired"):
                        continue
                    yield self.parse(job)
                except Exception as exc:  # noqa: BLE001
                    ctx.item_error(self.name, str(job.get("id")), exc)
            page += 1

    def _country_id(self, ctx: FetchContext, headers: dict[str, str]) -> int:
        data = ctx.http.get_json(f"{API}/core/geocountry/", params={"name": "Switzerland"}, headers=headers)
        for row in data.get("results", []):
            if str(row.get("name", "")).lower() == "switzerland" or row.get("code") in ("CH", "ch"):
                return int(row["id"])
        raise RuntimeError("Switzerland not found in foorilla geocountry list")

    def parse(self, job: dict[str, Any]) -> RawListing:
        company = job.get("company") or {}
        countries = [c.get("code") or c.get("name") for c in job.get("countries") or []]
        lo, hi, cur = job.get("salary_min"), job.get("salary_max"), job.get("salary_currency")
        salary_text = None
        if lo or hi:
            salary_text = f"{cur or ''} {lo} - {hi} per year" if lo and hi else f"{cur or ''} {lo or hi} per year"
        return RawListing(
            source=self.name,
            source_job_id=str(job["id"]),
            url=job.get("apply_url") or f"{self.base_url}/hiring/jobs/{job['id']}/",
            title=job["title"].strip(),
            company=company.get("name") if isinstance(company, dict) else None,
            location_text=job.get("location"),
            description_html=None,
            posted_at=parse_dt(job.get("published")),
            salary_text=salary_text.strip() if salary_text else None,
            employment_text=None,
            extra={
                "remote": WORK_MODES.get(job.get("work_mode")) or ("remote" if job.get("has_remote") else None),
                "seniority": job.get("experience_level"),
                "technologies": [t.get("name") for t in job.get("tags") or [] if t.get("name")],
                "topics": [t.get("name") for t in job.get("topics") or [] if t.get("name")],
                "countries": countries,
                "country": "CH" if "CH" in countries or len(countries) <= 1 else None,
                "language_code": job.get("language"),
                "agency": bool(company.get("agency")) if isinstance(company, dict) else None,
            },
        )
