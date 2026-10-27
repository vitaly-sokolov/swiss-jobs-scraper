"""Scrape run orchestration (§1, §8)."""

from __future__ import annotations

import logging
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html import escape
from urllib.parse import urlsplit

from sqlalchemy.orm import Session, sessionmaker

from jobscraper.adapters import ADAPTERS
from jobscraper.adapters.base import FetchContext, RawListing, SourceAdapter, has_enrich
from jobscraper.config import Settings, SourceConfig, Vocab
from jobscraper.db import repository as repo
from jobscraper.db.models import ScrapeRun
from jobscraper.fetch.browser import Browser
from jobscraper.fetch.http import HttpClient, SourceTimeout, Throttle
from jobscraper.normalize import Normalizer

log = logging.getLogger(__name__)

PARTIAL_ALERT_STREAK = 3


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class RunResult:
    source: str
    status: str
    counts: Counter[str] = field(default_factory=Counter)
    error: str | None = None


class Pipeline:
    def __init__(
        self,
        settings: Settings,
        vocab: Vocab,
        session_factory: sessionmaker[Session],
        *,
        http: HttpClient | None = None,
        browser: Browser | None = None,
        adapters: dict[str, type[SourceAdapter]] | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.settings = settings
        self.vocab = vocab
        self.session_factory = session_factory
        self.adapters = adapters or ADAPTERS
        self.clock = clock
        self.normalizer = Normalizer(vocab)
        self.http = http or HttpClient(
            user_agent=settings.user_agent,
            proxy=settings.proxy.httpx_proxy(),
            throttle=Throttle(settings.throttle.default_seconds_per_request),
            timeout=settings.timeouts.request_seconds,
        )
        self.browser = browser or Browser(
            user_agent=settings.user_agent,
            proxy_url=settings.proxy.browser_url if settings.proxy.enabled else None,
            page_load_timeout=settings.timeouts.page_load_seconds,
        )

    # ------------------------------------------------------------------ runs

    def enabled_sources(self) -> list[str]:
        return [name for name in self.adapters if self.source_config(name).enabled]

    def source_config(self, name: str) -> SourceConfig:
        return self.vocab.sources.get(name, SourceConfig(enabled=False))

    def run(self, names: list[str]) -> list[RunResult]:
        log.info("scrape start", extra={"sources": names, "egress": self.settings.proxy.describe()})
        global_deadline = time.monotonic() + self.settings.timeouts.global_minutes * 60
        results = []
        try:
            for name in names:
                results.append(self.run_source(name, global_deadline))
        finally:
            self.browser.quit()
            self.http.close()
        return results

    def run_source(self, name: str, global_deadline: float) -> RunResult:
        adapter = self.adapters[name]()
        cfg = self.source_config(name)
        with self.session_factory() as session:
            repo.ensure_source(session, name, adapter.base_url, adapter.fetch_method, cfg.enabled)
            run = repo.start_run(session, name, self.clock())
            session.commit()
            run_id, started_at = run.id, run.started_at

        if cfg.seconds_per_request is not None:
            self.http.throttle.set_interval(urlsplit(adapter.base_url).netloc, cfg.seconds_per_request)
        source_deadline = time.monotonic() + self.settings.timeouts.per_source_minutes * 60
        self.http.deadline = min(source_deadline, global_deadline)

        ctx = FetchContext(settings=self.settings, source_config=cfg, http=self.http, browser=self.browser)
        result = RunResult(source=name, status="ok")
        try:
            self.http.check_deadline()
            self._consume(adapter, ctx, result.counts)
            if result.counts["fetched"] == 0:
                raise RuntimeError("source returned no listings")
        except SourceTimeout:
            result.status, result.error = "failed", "timeout"
        except Exception as exc:  # noqa: BLE001 - source-level failure is recorded, not raised
            result.status, result.error = "failed", f"{type(exc).__name__}: {exc}"
            log.exception("source failed", extra={"source": name})
        finally:
            self.http.deadline = None
        result.counts["item_errors"] = ctx.item_errors
        if result.status == "ok" and ctx.item_errors:
            result.status = "partial"

        with self.session_factory() as session:
            now = self.clock()
            if result.status == "ok":
                result.counts["closed"] = repo.close_missing(
                    session, name, started_at, now, self.settings.closure_missed_runs
                )
            run = session.get_one(ScrapeRun, run_id)
            run.status = result.status
            run.finished_at = now
            run.error = result.error
            for key in ("fetched", "rejected", "inserted", "updated", "reopened", "closed", "item_errors"):
                setattr(run, key, result.counts[key])
            session.commit()
        log.info("source done", extra={"source": name, "status": result.status, **dict(result.counts)})
        return result

    def _consume(self, adapter: SourceAdapter, ctx: FetchContext, counts: Counter[str]) -> None:
        """Process listings in batches; on a mid-fetch failure keep the unfinished batch."""
        batch: list[RawListing] = []
        try:
            for raw in adapter.fetch(ctx):
                batch.append(raw)
                if len(batch) >= self.settings.batch_size:
                    self._process_batch(adapter, ctx, batch, counts)
                    batch = []
        except Exception:
            if batch:
                try:
                    # No detail fetches here: the deadline may already have passed.
                    self._process_batch(adapter, ctx, batch, counts, allow_enrich=False)
                except Exception:  # noqa: BLE001 - the original error is what gets reported
                    log.exception("could not store remaining batch", extra={"source": adapter.name})
            raise
        if batch:
            self._process_batch(adapter, ctx, batch, counts)

    def _process_batch(
        self,
        adapter: SourceAdapter,
        ctx: FetchContext,
        batch: list[RawListing],
        counts: Counter[str],
        allow_enrich: bool = True,
    ) -> None:
        counts["fetched"] += len(batch)
        unique: dict[str, RawListing] = {}
        for raw in batch:
            verdict = self.normalizer.prefilter(raw)
            if not verdict.keep or not self.normalizer.geography(raw):
                counts["rejected"] += 1
                continue
            unique[raw.source_job_id] = raw

        enrich = allow_enrich and has_enrich(adapter)
        with self.session_factory() as session:
            existing = repo.load_existing(session, adapter.name, unique)
            try:
                for job_id, raw in unique.items():
                    row = existing.get(job_id)
                    if enrich and (row is None or not row.is_active or row.details_fetched_at is None):
                        try:
                            raw = adapter.enrich(ctx, raw)  # type: ignore[attr-defined]
                        except SourceTimeout:
                            raise
                        except Exception as exc:  # noqa: BLE001 - keep the listing with its preview
                            ctx.item_error(adapter.name, job_id, exc)
                    try:
                        norm = self.normalizer.normalize(raw)
                    except Exception as exc:  # noqa: BLE001
                        ctx.item_error(adapter.name, job_id, exc)
                        continue
                    counts[repo.apply_listing(session, norm, row, self.clock())] += 1
            except SourceTimeout:
                session.commit()  # keep what this batch already processed
                raise
            session.commit()

    # ---------------------------------------------------------------- alerts

    def alerts(self, results: list[RunResult]) -> list[str]:
        """⚠️ messages for failed sources and partial streaks (§9)."""
        messages = []
        with self.session_factory() as session:
            for r in results:
                if r.status == "failed":
                    messages.append(f"⚠️ <b>{r.source}</b> failed: {escape(r.error or 'unknown error')}")
                elif r.status == "partial":
                    statuses = repo.recent_statuses(session, r.source, PARTIAL_ALERT_STREAK)
                    if len(statuses) == PARTIAL_ALERT_STREAK and all(s == "partial" for s in statuses):
                        messages.append(
                            f"⚠️ <b>{r.source}</b>: {PARTIAL_ALERT_STREAK} partial runs in a row "
                            f"({r.counts['item_errors']} item errors in the last run)"
                        )
        return messages

