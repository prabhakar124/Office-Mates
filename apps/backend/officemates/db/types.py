"""Column types shared by every model (BLUEPRINT section 4.2, MySQL conventions)."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import BINARY, Dialect
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.types import TypeDecorator


class UUIDBinary(TypeDecorator[uuid.UUID]):
    """``uuid.UUID`` in Python, ``BINARY(16)`` in MySQL (half the size of a text UUID)."""

    impl = BINARY(16)
    cache_ok = True

    def process_bind_param(self, value: uuid.UUID | None, dialect: Dialect) -> bytes | None:
        if value is None:
            return None
        if not isinstance(value, uuid.UUID):
            raise TypeError(f"expected uuid.UUID, got {type(value).__name__}")
        return value.bytes

    def process_result_value(self, value: bytes | None, dialect: Dialect) -> uuid.UUID | None:
        return None if value is None else uuid.UUID(bytes=bytes(value))


class UTCDateTime(TypeDecorator[datetime]):
    """Timezone-aware UTC datetimes stored as ``DATETIME(6)``.

    MySQL's DATETIME has no timezone, so the rule is enforced here: naive datetimes are
    rejected on the way in (they are almost always a bug), values are converted to UTC for
    storage, and they come back as aware UTC datetimes.
    """

    impl = DATETIME(fsp=6)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("naive datetime is not allowed; use an aware datetime (UTC)")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        return None if value is None else value.replace(tzinfo=UTC)


def utcnow() -> datetime:
    return datetime.now(UTC)
