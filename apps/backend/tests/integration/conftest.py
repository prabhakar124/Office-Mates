"""Fixtures for tests that need the real MySQL from Docker Compose.

Connection details come from, in order:
1. ``OM_TEST_DATABASE_URL`` / ``OM_TEST_DATABASE_MIGRATION_URL`` (used in CI), or
2. the repository's git-ignored ``.env`` (the passwords Docker Compose uses locally).

Everything runs against the separate ``officemates_test`` database. If MySQL is not
reachable the tests are skipped locally, but fail in CI so a broken setup is never silent.
"""

import asyncio
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from sqlalchemy import text

from officemates.db.session import create_engine

REPO_ROOT = Path(__file__).resolve().parents[4]
TEST_DATABASE = "officemates_test"


@dataclass(frozen=True)
class DbUrls:
    app: str  # app_rw: data only
    migrator: str  # migrator: may change the schema


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


def _resolve_urls() -> DbUrls | None:
    app = os.environ.get("OM_TEST_DATABASE_URL")
    migrator = os.environ.get("OM_TEST_DATABASE_MIGRATION_URL")
    if app and migrator:
        return DbUrls(app=app, migrator=migrator)

    env = _read_env_file(REPO_ROOT / ".env")
    app_pw, mig_pw = env.get("MYSQL_APP_PASSWORD"), env.get("MYSQL_MIGRATOR_PASSWORD")
    if not app_pw or not mig_pw:
        return None
    host = f"127.0.0.1:{env.get('MYSQL_HOST_PORT', '3310')}"
    return DbUrls(
        app=f"mysql+asyncmy://app_rw:{app_pw}@{host}/{TEST_DATABASE}",
        migrator=f"mysql+asyncmy://migrator:{mig_pw}@{host}/{TEST_DATABASE}",
    )


async def _can_connect(url: str) -> bool:
    engine = create_engine(url, pool_size=1, max_overflow=0)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - any failure means "not available"
        return False
    else:
        return True
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def db_urls() -> DbUrls:
    urls = _resolve_urls()
    reachable = urls is not None and asyncio.run(_can_connect(urls.migrator))
    if urls is None or not reachable:
        message = "MySQL test database not available (start it with: docker compose up -d mysql)"
        if os.environ.get("CI"):
            pytest.fail(message)
        pytest.skip(message)
    if f"/{TEST_DATABASE}" not in urls.app or f"/{TEST_DATABASE}" not in urls.migrator:
        pytest.fail(f"integration tests must only run against the {TEST_DATABASE} database")
    return urls


@pytest.fixture(scope="module")
def migrated_db(db_urls: DbUrls) -> Iterator[DbUrls]:
    """``officemates_test`` at the latest migration for one test module, then emptied."""
    from alembic import command

    from officemates.db.migrate import make_config

    config = make_config(db_urls.migrator)
    command.downgrade(config, "base")  # start clean even if a previous run was interrupted
    command.upgrade(config, "head")
    try:
        yield db_urls
    finally:
        command.downgrade(config, "base")
