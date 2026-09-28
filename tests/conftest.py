"""Shared pytest configuration.

Integration tests are marked ``integration`` and require PostgreSQL.
They skip when the database is unreachable unless ``AEGIS_REQUIRE_DB=1``
(which CI sets) — then they fail loudly instead of silently disappearing.
"""

from __future__ import annotations

import os
from functools import lru_cache

import pytest
from sqlalchemy import text


@lru_cache(maxsize=1)
def _database_available() -> bool:
    try:
        from aegis.db.session import engine

        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 - any driver error means "unavailable"
        return False


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "integration: requires a running PostgreSQL (AEGIS_REQUIRE_DB=1 to fail instead of skip)",
    )


def pytest_runtest_setup(item: pytest.Item) -> None:
    if "integration" not in item.keywords:
        return
    if _database_available():
        return
    if os.environ.get("AEGIS_REQUIRE_DB") == "1":
        pytest.fail("AEGIS_REQUIRE_DB=1 but PostgreSQL is unreachable")
    pytest.skip("PostgreSQL unavailable; integration test skipped")


@pytest.fixture
def db_available() -> bool:
    return _database_available()
