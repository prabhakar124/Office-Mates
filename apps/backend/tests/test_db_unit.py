"""Database helpers that can be tested without a running MySQL."""

import time
import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.dialects import mysql
from sqlalchemy.ext.asyncio import AsyncSession

from officemates.db.ids import uuid7
from officemates.db.session import create_engine, get_session
from officemates.db.types import UTCDateTime, UUIDBinary

DIALECT = mysql.dialect()


def test_uuid7_has_version_variant_and_current_timestamp() -> None:
    before = time.time_ns() // 1_000_000
    value = uuid7()
    after = time.time_ns() // 1_000_000
    assert value.version == 7
    assert value.variant == uuid.RFC_4122
    assert before <= value.int >> 80 <= after


def test_uuid7_sorts_by_creation_time_and_is_unique() -> None:
    first = uuid7()
    time.sleep(0.002)
    second = uuid7()
    assert first.bytes < second.bytes  # byte order is what InnoDB's BINARY(16) index uses
    assert len({uuid7() for _ in range(1000)}) == 1000


def test_uuid_binary_round_trip() -> None:
    column_type = UUIDBinary()
    value = uuid7()
    stored = column_type.process_bind_param(value, DIALECT)
    assert stored == value.bytes
    assert len(stored) == 16
    assert column_type.process_result_value(stored, DIALECT) == value
    assert column_type.process_bind_param(None, DIALECT) is None
    assert column_type.process_result_value(None, DIALECT) is None


def test_uuid_binary_rejects_strings() -> None:
    with pytest.raises(TypeError):
        UUIDBinary().process_bind_param(str(uuid7()), DIALECT)  # type: ignore[arg-type]


def test_utc_datetime_converts_to_utc_and_back() -> None:
    column_type = UTCDateTime()
    ist = timezone(timedelta(hours=5, minutes=30))
    local = datetime(2026, 11, 17, 10, 30, 0, 123456, tzinfo=ist)

    stored = column_type.process_bind_param(local, DIALECT)
    assert stored == datetime(2026, 11, 17, 5, 0, 0, 123456)  # noqa: DTZ001 - naive by design
    assert stored.tzinfo is None

    loaded = column_type.process_result_value(stored, DIALECT)
    assert loaded == local
    assert loaded.tzinfo is UTC


def test_utc_datetime_rejects_naive_values() -> None:
    with pytest.raises(ValueError, match="naive"):
        UTCDateTime().process_bind_param(datetime(2026, 1, 1), DIALECT)  # noqa: DTZ001


@pytest.mark.parametrize(
    "url",
    ["mysql+pymysql://u:p@h/db", "postgresql+asyncpg://u:p@h/db", "sqlite+aiosqlite:///x.db"],
)
def test_create_engine_rejects_other_drivers(url: str) -> None:
    with pytest.raises(ValueError, match="mysql\\+asyncmy"):
        create_engine(url)


def test_create_engine_never_shows_password_in_repr() -> None:
    engine = create_engine("mysql+asyncmy://app_rw:s3cret-pw@localhost:3306/officemates")
    assert "s3cret-pw" not in repr(engine)
    assert "s3cret-pw" not in str(engine.url)


def test_session_dependency_returns_503_when_database_not_configured(
    app: FastAPI, client: TestClient
) -> None:
    @app.get("/_test/db")
    async def needs_db(session: AsyncSession = Depends(get_session)) -> dict[str, bool]:  # noqa: B008
        return {"ok": True}

    resp = client.get("/_test/db")
    assert resp.status_code == 503
    assert resp.json()["type"].endswith("/database-unavailable")
