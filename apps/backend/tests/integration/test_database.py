"""Tests against the real MySQL 8.4 container (database: officemates_test)."""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from alembic import command
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Column, MetaData, String, Table, insert, select, text
from sqlalchemy.exc import DBAPIError

from officemates.core.config import Environment, Settings
from officemates.db.ids import uuid7
from officemates.db.migrate import make_config
from officemates.db.session import create_engine
from officemates.db.types import UTCDateTime, UUIDBinary
from officemates.main import create_app
from tests.integration.conftest import DbUrls

pytestmark = pytest.mark.integration


async def _scalar(url: str, sql: str) -> object:
    engine = create_engine(url, pool_size=1, max_overflow=0)
    try:
        async with engine.connect() as conn:
            return (await conn.execute(text(sql))).scalar_one_or_none()
    finally:
        await engine.dispose()


async def _execute(url: str, *statements: str) -> None:
    engine = create_engine(url, pool_size=1, max_overflow=0)
    try:
        async with engine.begin() as conn:
            for statement in statements:
                await conn.execute(text(statement))
    finally:
        await engine.dispose()


def test_sessions_use_utc_strict_mode_and_utf8mb4(db_urls: DbUrls) -> None:
    assert asyncio.run(_scalar(db_urls.app, "SELECT @@session.time_zone")) == "+00:00"
    sql_mode = str(asyncio.run(_scalar(db_urls.app, "SELECT @@session.sql_mode")))
    assert "STRICT_ALL_TABLES" in sql_mode
    assert asyncio.run(_scalar(db_urls.app, "SELECT @@character_set_connection")) == "utf8mb4"


def test_connected_as_the_restricted_accounts(db_urls: DbUrls) -> None:
    assert str(asyncio.run(_scalar(db_urls.app, "SELECT CURRENT_USER()"))).startswith("app_rw@")
    assert str(asyncio.run(_scalar(db_urls.migrator, "SELECT CURRENT_USER()"))).startswith(
        "migrator@"
    )


@pytest.mark.parametrize(
    "statement",
    [
        "CREATE TABLE _om_should_not_exist (id INT PRIMARY KEY)",
        "DROP TABLE IF EXISTS _om_privilege_probe",
        "ALTER TABLE _om_privilege_probe ADD COLUMN extra INT",
        "CREATE USER 'intruder'@'%' IDENTIFIED BY 'x'",
    ],
)
def test_app_account_cannot_change_schema(db_urls: DbUrls, statement: str) -> None:
    asyncio.run(
        _execute(
            db_urls.migrator,
            "CREATE TABLE IF NOT EXISTS _om_privilege_probe (id INT PRIMARY KEY)",
        )
    )
    try:
        with pytest.raises(DBAPIError) as excinfo:
            asyncio.run(_execute(db_urls.app, statement))
        assert "denied" in str(excinfo.value.orig).lower()
    finally:
        asyncio.run(_execute(db_urls.migrator, "DROP TABLE IF EXISTS _om_privilege_probe"))


def test_uuid_and_utc_columns_round_trip_through_mysql(db_urls: DbUrls) -> None:
    metadata = MetaData()
    table = Table(
        "_om_type_probe",
        metadata,
        Column("id", UUIDBinary, primary_key=True),
        Column("happened_at", UTCDateTime, nullable=False),
        Column("label", String(64), nullable=False),
    )
    ist = timezone(timedelta(hours=5, minutes=30))
    ids = [uuid7() for _ in range(3)]
    moment = datetime(2026, 11, 17, 10, 30, 0, 123456, tzinfo=ist)

    async def scenario() -> tuple[list[tuple[uuid.UUID, datetime, str]], dict[str, str]]:
        migrator = create_engine(db_urls.migrator, pool_size=1, max_overflow=0)
        app = create_engine(db_urls.app, pool_size=1, max_overflow=0)
        try:
            async with migrator.begin() as conn:
                await conn.run_sync(metadata.drop_all)
                await conn.run_sync(metadata.create_all)
            async with app.begin() as conn:  # data access as the restricted account
                await conn.execute(
                    insert(table),
                    [{"id": i, "happened_at": moment, "label": "नमस्ते 👋"} for i in ids],
                )
            async with app.connect() as conn:
                rows = (await conn.execute(select(table).order_by(table.c.id))).all()
                columns = (
                    await conn.execute(
                        text(
                            "SELECT column_name, column_type FROM information_schema.columns "
                            "WHERE table_schema = DATABASE() AND table_name = '_om_type_probe'"
                        )
                    )
                ).all()
            return [(r.id, r.happened_at, r.label) for r in rows], {
                str(name): str(ctype) for name, ctype in columns
            }
        finally:
            async with migrator.begin() as conn:
                await conn.run_sync(metadata.drop_all)
            await app.dispose()
            await migrator.dispose()

    rows, column_types = asyncio.run(scenario())

    assert column_types["id"] == "binary(16)"
    assert column_types["happened_at"] == "datetime(6)"
    assert [r[0] for r in rows] == sorted(ids, key=lambda u: u.bytes)
    for _, happened_at, label in rows:
        assert happened_at == moment  # same instant, microseconds preserved
        assert happened_at.utcoffset() == timedelta(0)
        assert label == "नमस्ते 👋"  # utf8mb4: non-Latin text and emoji survive


def test_migrations_upgrade_and_downgrade(db_urls: DbUrls) -> None:
    config = make_config(db_urls.migrator)
    try:
        command.upgrade(config, "head")
        version = asyncio.run(_scalar(db_urls.migrator, "SELECT version_num FROM alembic_version"))
        assert version == "0001"

        command.downgrade(config, "base")
        version = asyncio.run(_scalar(db_urls.migrator, "SELECT version_num FROM alembic_version"))
        assert version is None
    finally:
        asyncio.run(_execute(db_urls.migrator, "DROP TABLE IF EXISTS alembic_version"))


def test_migrations_refuse_the_app_account(db_urls: DbUrls) -> None:
    """Running migrations with the wrong (restricted) account must fail, not half-work."""
    with pytest.raises(DBAPIError):
        command.upgrade(make_config(db_urls.app), "head")


def test_readyz_reports_mysql(db_urls: DbUrls) -> None:
    settings = Settings(
        _env_file=None, environment=Environment.TEST, database_url=SecretStr(db_urls.app)
    )
    with TestClient(create_app(settings)) as client:
        resp = client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json()["checks"] == [
        {
            "name": "mysql",
            "status": "ok",
            "duration_ms": resp.json()["checks"][0]["duration_ms"],
            "error": None,
        }
    ]


def test_readyz_fails_when_mysql_is_unreachable() -> None:
    settings = Settings(
        _env_file=None,
        environment=Environment.TEST,
        database_url=SecretStr("mysql+asyncmy://app_rw:wrong-password@127.0.0.1:1/officemates"),
    )
    with TestClient(create_app(settings)) as client:
        resp = client.get("/readyz")
    assert resp.status_code == 503
    assert resp.json()["checks"][0]["status"] == "fail"
    assert "wrong-password" not in resp.text
