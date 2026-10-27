"""Adapter interface (§6.1).

Adapters fetch and parse only; they never touch the database. ``fetch`` yields
lazily so a mid-run failure keeps what was already fetched. A bad listing is
reported through ``ctx.item_error`` and skipped; source-level failures raise.

Optional ``enrich(ctx, listing)`` fetches the detail page for a listing. The
pipeline calls it only for listings that passed the filter and need details (new,
reopened, or never enriched), which keeps request counts low on large boards.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from jobscraper.config import Settings, SourceConfig
from jobscraper.fetch.browser import Browser
from jobscraper.fetch.http import HttpClient

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RawListing:
    source: str
    source_job_id: str
    url: str
    title: str
    company: str | None
    location_text: str | None
    description_html: str | None
    posted_at: datetime | None
    salary_text: str | None
    employment_text: str | None
    extra: dict = field(default_factory=dict)


@dataclass
class FetchContext:
    settings: Settings
    source_config: SourceConfig
    http: HttpClient
    browser: Browser
    item_errors: int = 0

    @property
    def options(self) -> dict[str, Any]:
        return self.source_config.options

    def item_error(self, source: str, ref: str, exc: BaseException) -> None:
        self.item_errors += 1
        log.warning("bad listing skipped", extra={"source": source, "ref": ref, "error": repr(exc)})


@runtime_checkable
class SourceAdapter(Protocol):
    name: str
    base_url: str
    fetch_method: str  # "http" | "selenium" | "api"

    def fetch(self, ctx: FetchContext) -> Iterator[RawListing]: ...


def has_enrich(adapter: SourceAdapter) -> bool:
    return callable(getattr(adapter, "enrich", None))


def parse_dt(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        from zoneinfo import ZoneInfo

        dt = dt.replace(tzinfo=ZoneInfo("Europe/Zurich"))
    return dt


_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_LD_JSON = re.compile(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', re.S)


def next_data(html: str) -> dict[str, Any]:
    match = _NEXT_DATA.search(html)
    if not match:
        raise ValueError("__NEXT_DATA__ not found")
    return json.loads(match.group(1))


def ld_json_objects(html: str) -> Iterator[dict[str, Any]]:
    for block in _LD_JSON.findall(html):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        items = data if isinstance(data, list) else data.get("@graph", [data])
        for item in items:
            if isinstance(item, dict):
                yield item


def job_posting_ld(html: str) -> dict[str, Any] | None:
    for obj in ld_json_objects(html):
        if obj.get("@type") == "JobPosting":
            return obj
    return None
