"""Repository and pipeline behaviour on real PostgreSQL (§8, §13)."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from jobscraper.adapters.base import FetchContext, RawListing
from jobscraper.config import SourceConfig, Vocab
from jobscraper.db import repository as repo
from jobscraper.db.models import Job, Notification, ScrapeRun
from jobscraper.db.session import LockHeld, single_instance
from jobscraper.fetch.browser import Browser
from jobscraper.fetch.http import HttpClient, SourceTimeout, Throttle
from jobscraper.pipeline import Pipeline


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 1, 7, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now

    def next_day(self) -> None:
        self.now += timedelta(days=1)


def listing(job_id: str, title: str = "Senior Backend Engineer (Python)", **kw) -> RawListing:
    defaults = dict(
        source="fake",
        source_job_id=job_id,
        url=f"https://example.org/{job_id}",
        title=title,
        company=kw.pop("company", "Acme AG"),
        location_text=kw.pop("location_text", "Zürich"),
        description_html="<p>Python, FastAPI, PostgreSQL</p>",
        posted_at=None,
        salary_text=None,
        employment_text="Full-Time",
        extra={"country": "CH"},
    )
    defaults.update(kw)
    return RawListing(**defaults)


class FakeAdapter:
    """Scriptable adapter: set ``listings`` / ``error`` before each run."""

    name = "fake"
    base_url = "https://example.org"
    fetch_method = "http"
    listings: list[RawListing] = []
    error: Exception | None = None
    bad_items = 0

    def fetch(self, ctx: FetchContext) -> Iterator[RawListing]:
        yield from type(self).listings
        for i in range(type(self).bad_items):
            ctx.item_error(self.name, f"bad{i}", ValueError("bad"))
        if type(self).error:
            raise type(self).error


class FakeEnrichAdapter(FakeAdapter):
    name = "fake_enrich"
    enriched: list[str] = []

    def enrich(self, ctx: FetchContext, raw: RawListing) -> RawListing:
        type(self).enriched.append(raw.source_job_id)
        return replace(raw, description_html="<p>full ad</p>", extra={**raw.extra, "enriched": True})


class OtherSource(FakeAdapter):
    name = "other"


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def pipeline(settings, session_factory, clock, tmp_path) -> Pipeline:
    vocab = Vocab()
    vocab.__dict__["sources"] = {
        n: SourceConfig(enabled=True) for n in ("fake", "fake_enrich", "other")
    }
    from tests.conftest import ROOT

    vocab.directory = ROOT / "config"
    FakeAdapter.listings, FakeAdapter.error, FakeAdapter.bad_items = [], None, 0
    OtherSource.listings = []
    FakeEnrichAdapter.listings, FakeEnrichAdapter.enriched = [], []
    return Pipeline(
        settings,
        vocab,
        session_factory,
        http=HttpClient(user_agent="t", proxy=None, throttle=Throttle(0)),
        browser=Browser(user_agent="t", proxy_url=None),
        adapters={"fake": FakeAdapter, "fake_enrich": FakeEnrichAdapter, "other": OtherSource},
        clock=clock,
    )


def run(pipeline: Pipeline, name: str = "fake"):
    return pipeline.run_source(name, global_deadline=float("inf"))


def jobs(session_factory, source: str = "fake") -> dict[str, Job]:
    with session_factory() as s:
        return {j.source_job_id: j for j in s.scalars(select(Job).where(Job.source == source))}


def test_new_job_is_pending(pipeline, session_factory):
    FakeAdapter.listings = [listing("1"), listing("2", title="Sales Manager")]
    result = run(pipeline)
    assert result.status == "ok"
    assert (result.counts["fetched"], result.counts["rejected"], result.counts["inserted"]) == (2, 1, 1)
    job = jobs(session_factory)["1"]
    assert job.is_active and job.notified_at is None and job.pending_event == "new"
    assert job.canton == "ZH" and "python" in job.tech_tags
    with session_factory() as s:
        r = s.scalars(select(ScrapeRun)).one()
        assert (r.status, r.inserted, r.rejected, r.finished_at is not None) == ("ok", 1, 1, True)


def test_update_refreshes_fields(pipeline, session_factory, clock):
    FakeAdapter.listings = [listing("1", salary_text=None)]
    run(pipeline)
    first_seen = jobs(session_factory)["1"].first_seen_at
    clock.next_day()
    FakeAdapter.listings = [listing("1", salary_text="CHF 120'000 - 140'000")]
    result = run(pipeline)
    assert result.counts["updated"] == 1
    job = jobs(session_factory)["1"]
    assert job.salary_min == 120000 and job.first_seen_at == first_seen and job.last_seen_at > first_seen


def test_closure_after_three_missed_ok_runs(pipeline, session_factory, clock):
    FakeAdapter.listings = [listing("1"), listing("2")]
    run(pipeline)
    FakeAdapter.listings = [listing("2")]
    for expected_missed in (1, 2):
        clock.next_day()
        run(pipeline)
        job = jobs(session_factory)["1"]
        assert job.is_active and job.missed_runs == expected_missed
    clock.next_day()
    result = run(pipeline)
    job = jobs(session_factory)["1"]
    assert result.counts["closed"] == 1
    assert not job.is_active and job.closed_at is not None
    assert jobs(session_factory)["2"].is_active


def test_partial_and_failed_runs_do_not_close(pipeline, session_factory, clock):
    FakeAdapter.listings = [listing("1"), listing("2")]
    run(pipeline)
    FakeAdapter.listings = [listing("2")]
    FakeAdapter.bad_items = 1
    for _ in range(4):
        clock.next_day()
        assert run(pipeline).status == "partial"
    FakeAdapter.bad_items = 0
    FakeAdapter.error = RuntimeError("blocked")
    clock.next_day()
    result = run(pipeline)
    assert result.status == "failed" and "blocked" in result.error
    job = jobs(session_factory)["1"]
    assert job.is_active and job.missed_runs == 0


def test_empty_result_is_failed(pipeline, session_factory):
    FakeAdapter.listings = []
    result = run(pipeline)
    assert result.status == "failed"


def test_timeout_keeps_processed_batch(pipeline, session_factory):
    class Timeout(FakeAdapter):
        def fetch(self, ctx):
            yield listing("1")
            raise SourceTimeout("deadline")

    pipeline.adapters["fake"] = Timeout
    result = run(pipeline)
    assert (result.status, result.error) == ("failed", "timeout")
    assert "1" in jobs(session_factory)


def test_reopen_notifies_again(pipeline, session_factory, clock):
    FakeAdapter.listings = [listing("1"), listing("2")]
    run(pipeline)
    with session_factory() as s:
        for job in s.scalars(select(Job)):
            repo.record_notification(s, job, chat_id="42", status="sent", message_id=1, error=None, now=clock())
        s.commit()
    FakeAdapter.listings = [listing("2")]
    for _ in range(3):
        clock.next_day()
        run(pipeline)
    assert not jobs(session_factory)["1"].is_active

    clock.next_day()
    FakeAdapter.listings = [listing("1"), listing("2")]
    result = run(pipeline)
    assert result.counts["reopened"] == 1
    job = jobs(session_factory)["1"]
    assert job.is_active and job.closed_at is None and job.reopened_at is not None
    assert job.notified_at is None and job.pending_event == "reopened"
    with session_factory() as s:
        assert [j.source_job_id for j in repo.pending_notifications(s)] == ["1"]


def test_duplicates_flagged_to_root_not_merged(pipeline, session_factory, clock):
    FakeAdapter.listings = [listing("a", title="Senior Backend Engineer (m/w/d) 100%")]
    run(pipeline)
    OtherSource.listings = [replace(listing("b", title="Senior Backend Engineer (f/m/x)"), source="other")]
    run(pipeline, "other")
    FakeEnrichAdapter.listings = [replace(listing("c", title="Senior Backend Engineer"), source="fake_enrich")]
    run(pipeline, "fake_enrich")

    root = jobs(session_factory)["a"]
    other = jobs(session_factory, "other")["b"]
    third = jobs(session_factory, "fake_enrich")["c"]
    assert root.duplicate_of_id is None
    assert other.duplicate_of_id == root.id
    assert third.duplicate_of_id == root.id  # never chains to "other"
    with session_factory() as s:
        assert len(repo.pending_notifications(s)) == 3  # both rows still notify (D8)
        assert repo.duplicate_sources(s, s.get(Job, other.id)) == ["fake", "fake_enrich"]


def test_duplicate_via_xref(pipeline, session_factory):
    FakeAdapter.listings = [listing("x", title="Backend Engineer", extra={"country": "CH", "xref": "uuid-1"})]
    run(pipeline)
    OtherSource.listings = [
        replace(listing("y", title="Backend-Entwickler Python", company="Acme Schweiz"), source="other",
                extra={"country": "CH", "xref": "uuid-1"})
    ]
    run(pipeline, "other")
    assert jobs(session_factory, "other")["y"].duplicate_of_id == jobs(session_factory)["x"].id


def test_enrich_only_when_needed(pipeline, session_factory, clock):
    FakeEnrichAdapter.listings = [
        replace(listing("1"), source="fake_enrich", extra={"country": "CH", "enriched": False})
    ]
    run(pipeline, "fake_enrich")
    assert FakeEnrichAdapter.enriched == ["1"]
    job = jobs(session_factory, "fake_enrich")["1"]
    assert job.description_html == "<p>full ad</p>" and job.details_fetched_at is not None

    clock.next_day()
    run(pipeline, "fake_enrich")
    assert FakeEnrichAdapter.enriched == ["1"]  # not fetched again
    # The preview from the listing must not overwrite the fetched full ad.
    assert jobs(session_factory, "fake_enrich")["1"].description_html == "<p>full ad</p>"


def test_alerts(pipeline, session_factory, clock):
    FakeAdapter.listings = [listing("1")]
    FakeAdapter.bad_items = 1
    results = []
    for _ in range(3):
        clock.next_day()
        results.append(run(pipeline))
    alerts = pipeline.alerts(results[-1:])
    assert len(alerts) == 1 and "3 partial runs" in alerts[0]

    FakeAdapter.error = RuntimeError("<blocked>")
    failed = run(pipeline)
    assert pipeline.alerts([failed]) == ["⚠️ <b>fake</b> failed: RuntimeError: &lt;blocked&gt;"]


def test_purge(pipeline, session_factory, clock):
    FakeAdapter.listings = [listing("1"), listing("2")]
    run(pipeline)
    now = clock.now + timedelta(days=400)
    with session_factory() as s:
        old = s.scalars(select(Job).where(Job.source_job_id == "1")).one()
        old.is_active, old.closed_at = False, now - timedelta(days=366)
        s.add(Notification(job_id=old.id, channel="telegram", chat_id="1", status="sent", event="new"))
        s.commit()
        raw_cleared, deleted = repo.purge(s, now, raw_days=90, inactive_days=365)
        s.commit()
    assert (raw_cleared, deleted) == (2, 1)
    remaining = jobs(session_factory)
    assert list(remaining) == ["2"] and remaining["2"].raw == {}


def test_single_instance_lock(engine):
    with single_instance(engine):
        with pytest.raises(LockHeld):
            with single_instance(engine):
                pass
    with single_instance(engine):  # released
        pass
