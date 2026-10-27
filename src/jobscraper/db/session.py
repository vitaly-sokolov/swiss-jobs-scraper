from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

# Arbitrary constant shared by jobs-scrape, jobs-notify and jobs-cleanup (§8).
ADVISORY_LOCK_KEY = 0x5157_4A42  # "SWJB"


def make_engine(database_url: str) -> Engine:
    return create_engine(database_url, pool_pre_ping=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


class LockHeld(RuntimeError):
    pass


@contextmanager
def single_instance(engine: Engine, key: int = ADVISORY_LOCK_KEY) -> Iterator[None]:
    """Hold a session-level advisory lock for the whole block.

    Session-level advisory locks belong to one connection, so the lock gets its own
    connection that stays checked out until the block exits. Work sessions use
    other pooled connections.
    """
    conn = engine.connect()
    try:
        got = conn.execute(select(func.pg_try_advisory_lock(key))).scalar_one()
        conn.commit()
        if not got:
            raise LockHeld("another jobscraper process holds the lock")
        try:
            yield
        finally:
            conn.execute(select(func.pg_advisory_unlock(key)))
            conn.commit()
    finally:
        conn.close()
