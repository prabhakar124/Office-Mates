"""Alembic environment (async engine, MySQL).

MySQL commits DDL implicitly: a migration that fails half-way is NOT rolled back.
Keep each revision small and single-purpose, and back up before migrating real data.
"""

import asyncio

from alembic import context
from sqlalchemy.engine import Connection

from officemates.db.models import Base
from officemates.db.session import create_engine

target_metadata = Base.metadata


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_online() -> None:
    url: str = context.config.attributes["database_url"]
    engine = create_engine(url, pool_size=1, max_overflow=0)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_run)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    raise SystemExit("Offline (--sql) migrations are not supported; run against a database.")

asyncio.run(_run_online())
