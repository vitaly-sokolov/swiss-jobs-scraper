"""Entry points: jobs-scrape, jobs-notify, jobs-migrate, jobs-cleanup."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from jobscraper.config import Settings, Vocab, load_settings
from sqlalchemy import inspect
from sqlalchemy.exc import OperationalError

from jobscraper.db.session import LockHeld, make_engine, make_session_factory, single_instance
from jobscraper.logging_setup import setup_logging

log = logging.getLogger("jobscraper")


def _bootstrap() -> tuple[Settings, Vocab]:
    setup_logging(os.environ.get("JOBS_LOG_LEVEL", "INFO"))
    return load_settings(), Vocab()


def _schema_ready(engine) -> bool:
    """Fail early with a clear message instead of an UndefinedTable traceback."""
    try:
        missing = {"sources", "jobs", "scrape_runs", "notifications"} - set(inspect(engine).get_table_names())
    except OperationalError as exc:
        log.error("cannot connect to the database (check database_url)", extra={"error": str(exc.orig)})
        return False
    if missing:
        log.error("database schema missing; run jobs-migrate first", extra={"missing_tables": sorted(missing)})
        return False
    return True


def scrape_main(argv: list[str] | None = None) -> int:
    from jobscraper.pipeline import Pipeline

    parser = argparse.ArgumentParser(prog="jobs-scrape", description="Fetch listings from job sources")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="run every enabled source")
    group.add_argument("--source", action="append", metavar="NAME", help="run one source (repeatable)")
    parser.add_argument("--no-alerts", action="store_true", help="do not send ⚠️ alerts to Telegram")
    args = parser.parse_args(argv)

    settings, vocab = _bootstrap()
    engine = make_engine(settings.database_url)
    if not _schema_ready(engine):
        return 1
    pipeline = Pipeline(settings, vocab, make_session_factory(engine))
    if args.all:
        names = pipeline.enabled_sources()
    else:
        unknown = [n for n in args.source if n not in pipeline.adapters]
        if unknown:
            parser.error(f"unknown source(s): {', '.join(unknown)}; known: {', '.join(pipeline.adapters)}")
        names = args.source
    try:
        with single_instance(engine):
            results = pipeline.run(names)
            alerts = pipeline.alerts(results)
    except LockHeld as exc:
        log.error(str(exc))
        return 2
    if alerts and not args.no_alerts:
        _send_alerts(settings, make_session_factory(engine), alerts)
    failed = [r.source for r in results if r.status == "failed"]
    # Exit 0 even when a source failed so `jobs-scrape && jobs-notify` still notifies
    # for the sources that worked; failures are reported via alerts.
    log.info("scrape finished", extra={"failed": failed})
    return 0


def _send_alerts(settings: Settings, session_factory, alerts: list[str]) -> None:
    from jobscraper.notify.telegram import Notifier

    try:
        notifier = Notifier(settings, session_factory)
    except RuntimeError as exc:
        log.error("cannot send alerts", extra={"error": str(exc), "alerts": alerts})
        return
    for message in alerts:
        notifier.send_alert(message)


def notify_main(argv: list[str] | None = None) -> int:
    from jobscraper.notify.telegram import Notifier

    parser = argparse.ArgumentParser(prog="jobs-notify", description="Send Telegram messages for pending jobs")
    parser.add_argument("--limit", type=int, default=None, help="send at most N messages")
    args = parser.parse_args(argv)

    settings, _ = _bootstrap()
    engine = make_engine(settings.database_url)
    if not _schema_ready(engine):
        return 1
    try:
        with single_instance(engine):
            Notifier(settings, make_session_factory(engine)).notify_pending(args.limit)
    except LockHeld as exc:
        log.error(str(exc))
        return 2
    except RuntimeError as exc:
        log.error(str(exc))
        return 1
    return 0


def cleanup_main(argv: list[str] | None = None) -> int:
    from datetime import UTC, datetime

    from jobscraper.db.repository import purge

    argparse.ArgumentParser(prog="jobs-cleanup", description="Apply retention rules (§15, D18)").parse_args(argv)
    settings, _ = _bootstrap()
    engine = make_engine(settings.database_url)
    if not _schema_ready(engine):
        return 1
    try:
        with single_instance(engine), make_session_factory(engine)() as session:
            raw_cleared, deleted = purge(
                session, datetime.now(UTC), settings.retention.raw_days, settings.retention.inactive_days
            )
            session.commit()
    except LockHeld as exc:
        log.error(str(exc))
        return 2
    log.info("cleanup done", extra={"raw_cleared": raw_cleared, "deleted": deleted})
    return 0


def migrate_main(argv: list[str] | None = None) -> int:
    from alembic import command
    from alembic.config import Config

    argparse.ArgumentParser(prog="jobs-migrate", description="alembic upgrade head").parse_args(argv)
    settings, _ = _bootstrap()
    ini = Path(os.environ.get("JOBS_ALEMBIC_INI", "alembic.ini"))
    cfg = Config(str(ini))
    cfg.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
    cfg.attributes["skip_logging_config"] = True  # keep JSON logging
    command.upgrade(cfg, "head")
    log.info("migrations applied")
    return 0


if __name__ == "__main__":
    sys.exit(scrape_main())
