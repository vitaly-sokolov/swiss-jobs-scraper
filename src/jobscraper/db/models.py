"""SQLAlchemy 2.0 ORM models (§7).

Additions over design v0.4:
- ``Job.country``            ISO country code; border-region jobs (D5) have no canton.
- ``Job.xref``               cross-board reference (JobCloud job UUID), used with
                             ``dedupe_key`` for duplicate flagging (D8).
- ``Job.pending_event``      ``new`` | ``reopened`` while a notification is owed (D9);
                             cleared once sent.
- ``Job.details_fetched_at`` when the full description was last fetched, so detail
                             pages are fetched once per job rather than every run.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Source(Base):
    __tablename__ = "sources"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    base_url: Mapped[str] = mapped_column(Text)
    fetch_method: Mapped[str] = mapped_column(String(16))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    jobs: Mapped[list["Job"]] = relationship(back_populates="source_rel")
    runs: Mapped[list["ScrapeRun"]] = relationship(back_populates="source_rel")


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("source", "source_job_id", name="uq_jobs_source_id"),
        Index("ix_jobs_dedupe_key", "dedupe_key"),
        Index("ix_jobs_xref", "xref"),
        Index("ix_jobs_active_first_seen", "is_active", "first_seen_at"),
        Index("ix_jobs_notify_pending", "notified_at", postgresql_where=text("notified_at IS NULL")),
        CheckConstraint("pending_event IN ('new','reopened')", name="ck_jobs_pending_event"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source: Mapped[str] = mapped_column(ForeignKey("sources.name"))
    source_job_id: Mapped[str] = mapped_column(String(255))
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    company: Mapped[str | None] = mapped_column(Text)
    location_text: Mapped[str | None] = mapped_column(Text)
    canton: Mapped[str | None] = mapped_column(String(2))
    country: Mapped[str | None] = mapped_column(String(2))
    remote: Mapped[str] = mapped_column(String(16), default="unknown")
    seniority: Mapped[str | None] = mapped_column(String(16))
    employment_type: Mapped[str | None] = mapped_column(String(16))
    salary_min: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    salary_max: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    salary_currency: Mapped[str | None] = mapped_column(String(3))
    salary_period: Mapped[str | None] = mapped_column(String(16))
    salary_text: Mapped[str | None] = mapped_column(Text)
    tech_tags: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    language: Mapped[str | None] = mapped_column(String(8))
    description_html: Mapped[str | None] = mapped_column(Text)
    description_hash: Mapped[str | None] = mapped_column(String(64))
    dedupe_key: Mapped[str] = mapped_column(String(64))
    xref: Mapped[str | None] = mapped_column(String(64))
    duplicate_of_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))  # D8
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    details_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    missed_runs: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reopened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pending_event: Mapped[str | None] = mapped_column(String(16))
    raw: Mapped[dict] = mapped_column(JSONB, default=dict)

    source_rel: Mapped[Source] = relationship(back_populates="jobs")
    notifications: Mapped[list["Notification"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", passive_deletes=True
    )


class ScrapeRun(Base):
    __tablename__ = "scrape_runs"
    __table_args__ = (
        CheckConstraint("status IN ('running','ok','partial','failed')", name="ck_run_status"),
        Index("ix_scrape_runs_source_started", "source", "started_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source: Mapped[str] = mapped_column(ForeignKey("sources.name"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16))
    fetched: Mapped[int] = mapped_column(Integer, default=0)
    rejected: Mapped[int] = mapped_column(Integer, default=0)
    inserted: Mapped[int] = mapped_column(Integer, default=0)
    updated: Mapped[int] = mapped_column(Integer, default=0)
    reopened: Mapped[int] = mapped_column(Integer, default=0)
    closed: Mapped[int] = mapped_column(Integer, default=0)
    item_errors: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)

    source_rel: Mapped[Source] = relationship(back_populates="runs")


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    channel: Mapped[str] = mapped_column(String(16))
    chat_id: Mapped[str] = mapped_column(String(64))
    message_id: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(16))  # sent | failed
    event: Mapped[str] = mapped_column(String(16))   # new | reopened
    error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    job: Mapped[Job] = relationship(back_populates="notifications")
