"""swissdevjobs.ch — public JSON feed ``/api/jobsLight`` (one request, all jobs).

The light feed has no description; title, technologies, category, salary and
workplace are enough for the tech filter and the notification.
"""

from __future__ import annotations

from collections.abc import Iterator

from jobscraper.adapters.base import FetchContext, RawListing, parse_dt

# metaCategory values that can contain backend / AI roles (D16). The keyword
# filter still runs afterwards.
DEFAULT_CATEGORIES = ["softwareeng", "mlaidata", "architectconsulting", "clouddevops"]


class SwissDevJobsAdapter:
    name = "swissdevjobs"
    base_url = "https://swissdevjobs.ch"
    fetch_method = "api"

    def fetch(self, ctx: FetchContext) -> Iterator[RawListing]:
        categories = set(ctx.options.get("meta_categories", DEFAULT_CATEGORIES))
        items = ctx.http.get_json(f"{self.base_url}/api/jobsLight")
        if not isinstance(items, list):
            raise ValueError("unexpected jobsLight payload")
        for item in items:
            try:
                if item.get("isPaused"):
                    continue
                if categories and item.get("metaCategory") not in categories:
                    continue
                yield self.parse(item)
            except Exception as exc:  # noqa: BLE001 - one bad listing must not stop the run
                ctx.item_error(self.name, str(item.get("_id")), exc)

    def parse(self, item: dict) -> RawListing:
        city = item.get("actualCity") or item.get("cityCategory")
        location = " ".join(p for p in (item.get("postalCode"), city) if p) or None
        return RawListing(
            source=self.name,
            source_job_id=str(item["_id"]),
            url=f"{self.base_url}/jobs/{item['jobUrl']}",
            title=item["name"].strip(),
            company=item.get("company"),
            location_text=location,
            description_html=None,
            posted_at=parse_dt(item.get("activeFrom")),
            salary_text=_salary_text(item),
            employment_text=item.get("jobType"),
            extra={
                "workplace": item.get("workplace"),
                "seniority": item.get("expLevel"),
                "technologies": item.get("technologies") or [],
                "filter_tags": item.get("filterTags") or [],
                "category": item.get("metaCategory"),
                "language_required": item.get("language"),
                "country": "CH",
            },
        )


def _salary_text(item: dict) -> str | None:
    lo, hi = item.get("annualSalaryFrom"), item.get("annualSalaryTo")
    if lo or hi:
        if lo and hi and lo != hi:
            return f"CHF {lo} - {hi} per year"
        return f"CHF {lo or hi} per year"
    lo, hi = item.get("contractRateFrom"), item.get("contractRateTo")
    if lo or hi:
        unit = {"hourly": "hour", "daily": "day"}.get(str(item.get("contractRateType")).lower(), "hour")
        return f"CHF {lo or hi}{f' - {hi}' if lo and hi and lo != hi else ''} per {unit}"
    return None
