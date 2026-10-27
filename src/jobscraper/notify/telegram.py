"""Per-job Telegram messages (§9, D7). Alerts go to the same private chat (D15)."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from html import escape as _html_escape

import httpx
from sqlalchemy.orm import Session, sessionmaker

from jobscraper.config import Settings
from jobscraper.db import repository as repo
from jobscraper.db.models import Job

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
MAX_TAGS = 6

SOURCE_LABELS = {
    "swissdevjobs": "SwissDevJobs",
    "jobs_ch": "jobs.ch",
    "jobup": "jobup.ch",
    "ictjobs": "ictjobs.ch",
    "ictcareer": "ictcareer.ch",
    "foorilla": "foorilla",
}
REMOTE_LABELS = {"onsite": "on-site", "hybrid": "hybrid", "remote": "remote"}
PERIOD_LABELS = {"year": "year", "month": "month", "day": "day", "hour": "hour"}


def escape(text: str, quote: bool = False) -> str:
    """Telegram HTML needs only &, <, > escaped in text; quotes too inside attributes."""
    return _html_escape(text, quote=quote)


@dataclass(frozen=True)
class SendResult:
    ok: bool
    message_id: int | None = None
    error: str | None = None


class TelegramClient:
    def __init__(
        self,
        bot_token: str,
        *,
        proxy: str | None = None,
        api_base: str = "https://api.telegram.org",
        sleep: Callable[[float], None] = time.sleep,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._url = f"{api_base}/bot{bot_token}/sendMessage"
        self._sleep = sleep
        self._client = httpx.Client(timeout=20, proxy=proxy, transport=transport)

    def close(self) -> None:
        self._client.close()

    def send(self, chat_id: str, html: str) -> SendResult:
        payload = {
            "chat_id": chat_id,
            "text": html,
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True},
        }
        error = "unknown"
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = self._client.post(self._url, json=payload)
            except httpx.TransportError as exc:
                error = f"transport: {exc}"
                self._sleep(2**attempt)
                continue
            try:
                body = response.json()
            except ValueError:
                body = {}
            if response.status_code == 200 and body.get("ok"):
                return SendResult(True, message_id=body.get("result", {}).get("message_id"))
            error = f"{response.status_code}: {body.get('description') or response.text[:200]}"
            if response.status_code == 429:
                retry_after = float((body.get("parameters") or {}).get("retry_after") or 2**attempt)
                log.warning("telegram 429", extra={"retry_after": retry_after, "attempt": attempt})
                self._sleep(retry_after)
                continue
            if response.status_code >= 500:
                self._sleep(2**attempt)
                continue
            break  # 4xx other than 429: retrying will not help
        return SendResult(False, error=error)


def _money(value: Decimal) -> str:
    return f"{int(value):,}".replace(",", "'") if value == value.to_integral() else f"{value:,.2f}".replace(",", "'")


def format_salary(job: Job) -> str | None:
    """Published salary only (D11): parsed range if available, else the raw text."""
    if job.salary_min is not None:
        span = _money(job.salary_min)
        if job.salary_max is not None and job.salary_max != job.salary_min:
            span += f"–{_money(job.salary_max)}"
        period = PERIOD_LABELS.get(job.salary_period or "", "")
        return f"{job.salary_currency or ''} {span}{f' / {period}' if period else ''}".strip()
    return job.salary_text or None


def format_message(job: Job, also_on: list[str]) -> str:
    head = "🆕" if job.pending_event != "reopened" else "🔁 reopened"
    lines = [f"{head} <b>{escape(job.title)}</b>"]
    where = job.canton or job.location_text or job.country
    meta = [escape(job.company) if job.company else None, f"📍 {escape(where)}" if where else None]
    if remote := REMOTE_LABELS.get(job.remote):
        meta.append(f"🏠 {remote}")
    lines.append(" · ".join(m for m in meta if m))
    if salary := format_salary(job):
        lines.append(f"💰 {escape(salary)}")
    if job.tech_tags:
        lines.append("🏷 " + ", ".join(escape(t) for t in job.tech_tags[:MAX_TAGS]))
    source = SOURCE_LABELS.get(job.source, job.source)
    footer = f"🔗 <a href=\"{escape(job.url, quote=True)}\">{escape(source)}</a>"
    if also_on:
        footer += " · also on " + ", ".join(escape(SOURCE_LABELS.get(s, s)) for s in also_on)
    lines.append(footer)
    return "\n".join(lines)


class Notifier:
    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker[Session],
        client: TelegramClient | None = None,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        tg = settings.telegram
        if not tg.bot_token or not tg.chat_id:
            raise RuntimeError("telegram.bot_token and telegram.chat_id must be set in config.yaml")
        self.chat_id = tg.chat_id
        self.interval = tg.seconds_between_messages
        self.session_factory = session_factory
        self.client = client or TelegramClient(
            tg.bot_token.get_secret_value(),
            proxy=settings.proxy.httpx_proxy() if tg.use_proxy else None,
            api_base=tg.api_base,
        )
        self._sleep = sleep
        self._clock = clock

    def send_alert(self, html: str) -> bool:
        result = self.client.send(self.chat_id, html)
        if not result.ok:
            log.error("alert not sent", extra={"error": result.error})
        return result.ok

    def notify_pending(self, limit: int | None = None) -> tuple[int, int]:
        sent = failed = 0
        with self.session_factory() as session:
            ids = [job.id for job in repo.pending_notifications(session, limit)]
        for index, job_id in enumerate(ids):
            if index:
                self._sleep(self.interval)
            with self.session_factory() as session:
                job = session.get_one(Job, job_id)
                result = self.client.send(self.chat_id, format_message(job, repo.duplicate_sources(session, job)))
                repo.record_notification(
                    session,
                    job,
                    chat_id=self.chat_id,
                    status="sent" if result.ok else "failed",
                    message_id=result.message_id,
                    error=result.error,
                    now=self._clock(),
                )
                session.commit()
            if result.ok:
                sent += 1
            else:
                failed += 1
                log.warning("notification failed", extra={"job_id": job_id, "error": result.error})
        log.info("notify done", extra={"sent": sent, "failed": failed})
        return sent, failed
