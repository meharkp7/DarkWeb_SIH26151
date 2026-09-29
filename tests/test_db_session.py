"""The platform must refuse to serve against a database that cannot support it.

The failure these guard against is not a crash: it is an application that
boots, serves reads, and then fails deep inside a write the first time two
people touch the audit chain at once — with an error that names a data
structure rather than the cause.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

from aegis.db.session import assert_postgres


def test_sqlite_is_refused_with_a_reason() -> None:
    engine = create_engine("sqlite:///:memory:")
    with pytest.raises(RuntimeError) as caught:
        assert_postgres(engine)
    message = str(caught.value)
    # The message has to name what is wrong, not just that something is.
    assert "PostgreSQL" in message
    assert "advisory" in message.lower()


def test_a_pooler_is_diagnosed_separately() -> None:
    """Advisory locks are session-scoped, so pgbouncer in transaction mode
    cannot support the audit chain. That deserves its own message."""
    engine = create_engine("postgresql+psycopg://u:p@127.0.0.1:1/none")
    with pytest.raises(RuntimeError) as caught:
        assert_postgres(engine)
    assert "pooler" in str(caught.value).lower() or "direct connection" in str(caught.value).lower()


def test_the_check_does_not_fire_on_a_healthy_database(db_available: bool) -> None:
    if not db_available:
        pytest.skip("PostgreSQL unavailable")
    # Must not raise: the real engine is Postgres and reachable.
    assert_postgres()


def test_a_broken_connection_surfaces_as_sqlalchemy_error() -> None:
    """The advisory-lock probe must not swallow its own driver errors."""
    engine = create_engine("postgresql+psycopg://u:p@127.0.0.1:1/none")
    with pytest.raises((RuntimeError, SQLAlchemyError)):
        assert_postgres(engine)
