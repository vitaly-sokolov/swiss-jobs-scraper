from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, text

from jobscraper.adapters.base import FetchContext
from jobscraper.config import Settings, SourceConfig, Vocab
from jobscraper.db.models import Base
from jobscraper.db.session import make_engine, make_session_factory
from jobscraper.fetch.browser import Browser
from jobscraper.fetch.http import HttpClient, Throttle

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def vocab() -> Vocab:
    return Vocab(ROOT / "config")


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_url="postgresql+psycopg://unused/unused",
        contact_email="test@example.com",
        telegram={"bot_token": "TEST", "chat_id": "42", "seconds_between_messages": 0},
        throttle={"default_seconds_per_request": 0},
    )


@pytest.fixture
def http() -> Iterator[HttpClient]:
    client = HttpClient(user_agent="test", proxy=None, throttle=Throttle(0), sleep=lambda _: None)
    yield client
    client.close()


@pytest.fixture
def make_ctx(settings: Settings, http: HttpClient):
    def _make(options: dict | None = None) -> FetchContext:
        return FetchContext(
            settings=settings,
            source_config=SourceConfig(options=options or {}),
            http=http,
            browser=Browser(user_agent="test", proxy_url=None),
        )

    return _make


# --------------------------------------------------------------------- database
# Repository tests need real PostgreSQL (§13). Order of preference:
#   1. TEST_DATABASE_URL (e.g. a local server or CI service container)
#   2. Testcontainers, when Docker is available
# Otherwise the tests are skipped.


@pytest.fixture(scope="session")
def pg_url() -> Iterator[str]:
    if url := os.environ.get("TEST_DATABASE_URL"):
        yield url
        return
    if not shutil.which("docker"):
        pytest.skip("no TEST_DATABASE_URL and no Docker for Testcontainers")
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:16", driver="psycopg") as pg:
        yield pg.get_connection_url()


@pytest.fixture(scope="session")
def engine(pg_url: str) -> Iterator[Engine]:
    eng = make_engine(pg_url)
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session_factory(engine: Engine):
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE notifications, scrape_runs, jobs, sources RESTART IDENTITY CASCADE"))
    return make_session_factory(engine)
