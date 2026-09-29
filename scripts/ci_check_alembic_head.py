"""Fail unless `alembic current` and `alembic heads` name the same revision.

`alembic upgrade head` returning 0 only proves the command did not raise; a
migration that silently fails to stamp alembic_version still exits clean. The
CI migrations gate needs the stronger statement.
"""

from __future__ import annotations

import sys

from alembic.config import Config
from alembic.script import ScriptDirectory


def _head() -> str:
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    heads = script.get_heads()
    if len(heads) != 1:
        raise SystemExit(f"expected exactly one head revision, found {heads}")
    return heads[0]


def main() -> int:
    from sqlalchemy import text

    from aegis.db.session import engine
    from aegis.settings import settings

    head = _head()
    with engine.connect() as connection:
        stamped = (
            connection.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
        )

    if list(stamped) != [head]:
        print(f"alembic_version is {list(stamped)} but head is {head}", file=sys.stderr)
        return 1
    print(f"database is stamped at head: {head}")
    print(f"database url: {settings.database_url.split('@')[-1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
