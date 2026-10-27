"""Persistence logic (§8). All queries go through the ORM; callers own the session."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from jobscraper.db.models import Job, Notification, ScrapeRun, Source
from jobscraper.normalize import NormalizedJob

Outcome = Literal["inserted", "updated", "reopened"]

# Fields refreshed on every sighting (§8 step 5). Identity fields and the
# lifecycle columns are managed separately.
_MUTABLE = (
    "url", "title", "company", "location_text", "canton", "country", "remote", "seniority",
    "employment_type", "salary_min", "salary_max", "salary_currency", "salary_period", "salary_text",
    "tech_tags", "language", "dedupe_key", "xref", "posted_at", "raw",
)


def ensure_source(session: Session, name: str, base_url: str, fetch_method: str, enabled: bool) -> Source:
    source = session.get(Source, name)
    if source is None:
        source = Source(name=name, base_url=base_url, fetch_method=fetch_method, enabled=enabled)
        session.add(source)
    else:
        source.base_url, source.fetch_method, source.enabled = base_url, fetch_method, enabled
    return source


def start_run(session: Session, source: str, now: datetime) -> ScrapeRun:
    run = ScrapeRun(source=source, started_at=now, status="running")
    session.add(run)
    session.flush()
    return run


def load_existing(session: Session, source: str, source_job_ids: Iterable[str]) -> dict[str, Job]:
    ids = list(set(source_job_ids))
    if not ids:
        return {}
    rows = session.scalars(select(Job).where(Job.source == source, Job.source_job_id.in_(ids)))
    return {job.source_job_id: job for job in rows}


def apply_listing(session: Session, norm: NormalizedJob, existing: Job | None, now: datetime) -> Outcome:
    if existing is None:
        job = Job(
            source=norm.source,
            source_job_id=norm.source_job_id,
            first_seen_at=now,
            last_seen_at=now,
            missed_runs=0,
            is_active=True,
            pending_event="new",
            notified_at=None,
        )
        _copy_fields(job, norm, now)
        job.duplicate_of_id = find_duplicate_root(session, job)
        session.add(job)
        return "inserted"

    reopened = not existing.is_active
    _copy_fields(existing, norm, now)
    existing.last_seen_at = now
    existing.missed_runs = 0
    if reopened:
        # D9: a returning job is notified again.
        existing.is_active = True
        existing.closed_at = None
        existing.reopened_at = now
        existing.notified_at = None
        existing.pending_event = "reopened"
        return "reopened"
    return "updated"


def _copy_fields(job: Job, norm: NormalizedJob, now: datetime) -> None:
    for name in _MUTABLE:
        setattr(job, name, getattr(norm, name))
    # Keep a previously fetched full description when this sighting only has the
    # listing preview.
    if norm.enriched or job.details_fetched_at is None:
        job.description_html = norm.description_html
        job.description_hash = norm.description_hash
    if norm.details_fetched:
        job.details_fetched_at = now


def find_duplicate_root(session: Session, job: Job) -> int | None:
    """D8: point at the earliest *root* row from another source with the same key.

    Matches on ``dedupe_key`` or, when present, on ``xref`` (JobCloud UUID).
    Rows that are themselves duplicates resolve to their root, so chains never form.
    """
    conditions = [Job.dedupe_key == job.dedupe_key]
    if job.xref:
        conditions.append(Job.xref == job.xref)
    match = session.scalars(
        select(Job)
        .where(Job.source != job.source, or_(*conditions))
        .order_by(Job.first_seen_at, Job.id)
        .limit(1)
    ).first()
    if match is None:
        return None
    return match.duplicate_of_id or match.id


def close_missing(session: Session, source: str, run_started_at: datetime, now: datetime, threshold: int) -> int:
    """§8 step 8 — only call after an ``ok`` run."""
    session.execute(
        update(Job)
        .where(Job.source == source, Job.is_active.is_(True), Job.last_seen_at < run_started_at)
        .values(missed_runs=Job.missed_runs + 1)
        .execution_options(synchronize_session=False)
    )
    result = session.execute(
        update(Job)
        .where(Job.source == source, Job.is_active.is_(True), Job.missed_runs >= threshold)
        .values(is_active=False, closed_at=now)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount or 0


def recent_statuses(session: Session, source: str, limit: int) -> list[str]:
    return list(
        session.scalars(
            select(ScrapeRun.status)
            .where(ScrapeRun.source == source, ScrapeRun.status != "running")
            .order_by(ScrapeRun.started_at.desc(), ScrapeRun.id.desc())
            .limit(limit)
        )
    )


def pending_notifications(session: Session, limit: int | None = None) -> Sequence[Job]:
    stmt = (
        select(Job)
        .where(Job.notified_at.is_(None), Job.is_active.is_(True), Job.pending_event.is_not(None))
        .order_by(Job.first_seen_at, Job.id)
    )
    if limit:
        stmt = stmt.limit(limit)
    return session.scalars(stmt).all()


def duplicate_sources(session: Session, job: Job) -> list[str]:
    """Other sources carrying the same posting (root and siblings), for "also on …"."""
    root_id = job.duplicate_of_id or job.id
    rows = session.scalars(
        select(Job.source)
        .where(or_(Job.id == root_id, Job.duplicate_of_id == root_id), Job.id != job.id, Job.source != job.source)
        .distinct()
    )
    return sorted(rows)


def record_notification(
    session: Session,
    job: Job,
    *,
    chat_id: str,
    status: Literal["sent", "failed"],
    message_id: int | None,
    error: str | None,
    now: datetime,
) -> None:
    session.add(
        Notification(
            job_id=job.id,
            channel="telegram",
            chat_id=chat_id,
            message_id=message_id,
            status=status,
            event=job.pending_event or "new",
            error=error,
            sent_at=now,
        )
    )
    if status == "sent":
        job.notified_at = now
        job.pending_event = None


def purge(session: Session, now: datetime, raw_days: int, inactive_days: int) -> tuple[int, int]:
    """§15 / D18: drop ``raw`` after ``raw_days``; delete jobs inactive for ``inactive_days``."""
    raw_cleared = session.execute(
        update(Job)
        .where(Job.first_seen_at < now - timedelta(days=raw_days), Job.raw != {})
        .values(raw={})
        .execution_options(synchronize_session=False)
    ).rowcount
    deleted = session.execute(
        delete(Job)
        .where(Job.is_active.is_(False), Job.closed_at < now - timedelta(days=inactive_days))
        .execution_options(synchronize_session=False)
    ).rowcount
    return raw_cleared or 0, deleted or 0
