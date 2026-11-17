"""Async engine and session management for MySQL."""

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from officemates.core.errors import AppError
from officemates.core.health import CheckFn

REQUIRED_DRIVER = "mysql+asyncmy"
SESSION_INIT_SQL = "SET time_zone = '+00:00', sql_mode = CONCAT(@@sql_mode, ',STRICT_ALL_TABLES')"


class DatabaseNotConfiguredError(AppError):
    status = 503
    code = "database-unavailable"
    title = "Database is not configured"


def create_engine(url: str, *, pool_size: int = 5, max_overflow: int = 5) -> AsyncEngine:
    parsed = make_url(url)
    if parsed.drivername != REQUIRED_DRIVER:
        raise ValueError(f"database URL must use {REQUIRED_DRIVER}://, got {parsed.drivername}://")
    return create_async_engine(
        parsed.update_query_dict({"charset": "utf8mb4"}),
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_pre_ping=True,  # replace connections MySQL closed while idle
        pool_recycle=1800,
        connect_args={
            # Every session speaks UTC and rejects silently-truncated or invalid data.
            "init_command": SESSION_INIT_SQL,
            "connect_timeout": 5,
        },
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request, rolled back on error.

    Endpoints commit explicitly. Tenant scoping is layered on top of this in Phase 1.
    """
    factory: async_sessionmaker[AsyncSession] | None = request.app.state.session_factory
    if factory is None:
        raise DatabaseNotConfiguredError
    async with factory() as session:
        try:
            yield session
        except BaseException:
            await session.rollback()
            raise


def database_readiness_check(engine: AsyncEngine) -> CheckFn:
    async def check() -> None:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    return check
