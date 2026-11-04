"""Alembic environment.

At runtime the app passes an open connection via ``config.attributes["connection"]``.
From the CLI (``alembic -c alembic.ini ...``) the URL comes from the normal settings loader.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import Connection

import magarr.domain.models  # noqa: F401  (registers tables on Base.metadata)
from magarr.core.db import Base, create_db_engine

target_metadata = Base.metadata


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,  # SQLite cannot ALTER most things in place
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = context.config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return

    from magarr.core.config import load_settings

    engine = create_db_engine(load_settings().database_url)
    with engine.begin() as conn:
        _run(conn)


if context.is_offline_mode():
    raise SystemExit("Offline migrations are not supported")
run_migrations_online()
