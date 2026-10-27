from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from jobscraper.db.models import Job, Notification, Source
from jobscraper.notify.telegram import Notifier, TelegramClient, format_message

URL = "https://api.telegram.org/botTEST/sendMessage"


def make_job(**kw) -> Job:
    defaults = dict(
        id=1, source="jobs_ch", source_job_id="x", url="https://www.jobs.ch/en/vacancies/detail/x/",
        title="Senior Backend Engineer <Python>", company="Acme & Co", location_text="Zürich", canton="ZH",
        country="CH", remote="hybrid", salary_min=Decimal("120000.00"), salary_max=Decimal("140000.00"),
        salary_currency="CHF", salary_period="year", salary_text="CHF 120k-140k",
        tech_tags=["python", "fastapi", "postgresql"], pending_event="new",
    )
    defaults.update(kw)
    return Job(**defaults)


def test_format_new_message():
    text = format_message(make_job(), also_on=["ictcareer"])
    assert text.startswith("🆕 <b>Senior Backend Engineer &lt;Python&gt;</b>")
    assert "Acme &amp; Co · 📍 ZH · 🏠 hybrid" in text
    assert "💰 CHF 120'000–140'000 / year" in text
    assert "🏷 python, fastapi, postgresql" in text
    assert '<a href="https://www.jobs.ch/en/vacancies/detail/x/">jobs.ch</a> · also on ictcareer.ch' in text


def test_format_reopened_without_salary():
    text = format_message(make_job(pending_event="reopened", salary_min=None, salary_max=None, salary_text=None), [])
    assert text.startswith("🔁 reopened <b>")
    assert "💰" not in text  # D11: only published salaries


def responder(responses: list[httpx.Response]):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return responses.pop(0)

    return handler, calls


def test_client_honours_retry_after():
    sleeps: list[float] = []
    handler, calls = responder([
        httpx.Response(429, json={"ok": False, "description": "Too Many Requests", "parameters": {"retry_after": 7}}),
        httpx.Response(200, json={"ok": True, "result": {"message_id": 99}}),
    ])
    client = TelegramClient("TEST", sleep=sleeps.append, transport=httpx.MockTransport(handler))
    result = client.send("42", "hi")
    assert result.ok and result.message_id == 99
    assert sleeps == [7.0] and len(calls) == 2


def test_client_gives_up_on_400():
    handler, calls = responder([httpx.Response(400, json={"ok": False, "description": "Bad Request: chat not found"})])
    result = TelegramClient("TEST", sleep=lambda _: None, transport=httpx.MockTransport(handler)).send("42", "hi")
    assert not result.ok and "chat not found" in result.error and len(calls) == 1


@pytest.fixture
def seeded(session_factory):
    with session_factory() as s:
        s.add(Source(name="jobs_ch", base_url="https://www.jobs.ch", fetch_method="api"))
        for i in (1, 2):
            s.add(Job(source="jobs_ch", source_job_id=str(i), url=f"https://e.org/{i}", title=f"Backend {i}",
                      dedupe_key=str(i), pending_event="new", first_seen_at=datetime(2026, 10, i, tzinfo=UTC)))
        s.add(Job(source="jobs_ch", source_job_id="3", url="https://e.org/3", title="Closed", dedupe_key="3",
                  pending_event="new", is_active=False))
        s.commit()
    return session_factory


def test_notify_pending_success_and_failure(settings, seeded):
    handler, calls = responder([
        httpx.Response(200, json={"ok": True, "result": {"message_id": 10}}),
        httpx.Response(400, json={"ok": False, "description": "Bad Request"}),
    ])
    client = TelegramClient("TEST", sleep=lambda _: None, transport=httpx.MockTransport(handler))
    sent, failed = Notifier(settings, seeded, client, sleep=lambda _: None).notify_pending()
    assert (sent, failed) == (1, 1)
    assert len(calls) == 2  # inactive job is not sent

    with seeded() as s:
        by_id = {j.source_job_id: j for j in s.scalars(select(Job))}
        assert by_id["1"].notified_at is not None and by_id["1"].pending_event is None
        assert by_id["2"].notified_at is None and by_id["2"].pending_event == "new"  # retried next run
        rows = s.scalars(select(Notification).order_by(Notification.id)).all()
        assert [(r.status, r.event, r.message_id) for r in rows] == [("sent", "new", 10), ("failed", "new", None)]


def test_notifier_requires_config(settings, session_factory):
    settings.telegram.chat_id = None
    with pytest.raises(RuntimeError):
        Notifier(settings, session_factory)
