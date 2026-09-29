"""Engine construction and a startup check that the database is actually Postgres.

AEGIS uses Postgres-specific behaviour in three places that will not fail
loudly on another engine:

* the audit hash chain takes a **session-scoped advisory lock**
  (``pg_advisory_xact_lock``), so two writers cannot interleave;
* ``collection_jobs`` and several analytics queries use ``DISTINCT ON`` and
  window functions;
* evidence, actor and infrastructure metadata are ``JSONB`` with containment
  queries against them.

Against SQLite or MySQL the first two fail at *call* time, deep inside a write,
with an error that names a data structure rather than the cause. Refusing at
startup with a message that names the cause is the difference between a
two-minute diagnosis and an afternoon.
"""

from __future__ import annotations

import logging
from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from aegis.settings import settings

logger = logging.getLogger(__name__)

engine: Engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def assert_postgres(target: Engine | None = None) -> None:
    """Raise unless the connected database is PostgreSQL.

    Called from the app's startup hook. Cheap: one round trip that opens a
    connection the pool would have opened anyway.
    """
    bound = target if target is not None else engine
    if bound.dialect.name != "postgresql":
        raise RuntimeError(
            f"AEGIS requires PostgreSQL; the configured database reports dialect "
            f"{bound.dialect.name!r}. Advisory locks, DISTINCT ON, window "
            f"functions and JSONB containment are all used on live paths, and "
            f"none of them degrade safely on another engine."
        )
    try:
        with bound.connect() as connection:
            connection.execute(text("SELECT pg_advisory_xact_lock(0)"))
    except SQLAlchemyError as error:  # pragma: no cover - depends on host
        raise RuntimeError(
            "AEGIS could not obtain a PostgreSQL advisory lock. This usually "
            "means the connection string points at a pooler (pgbouncer in "
            "transaction mode) rather than at a direct connection: advisory "
            "locks are session-scoped and cannot survive a shared session."
        ) from error


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
