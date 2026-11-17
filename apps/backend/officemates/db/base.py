"""Declarative base and mixins every model builds on.

Models are added from Phase 1. Import them in ``officemates.db.models`` so Alembic's
autogenerate can see them through ``Base.metadata``.
"""

import uuid
from datetime import datetime

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from officemates.db.ids import uuid7
from officemates.db.types import UTCDateTime, UUIDBinary, utcnow

# Explicit constraint names make migrations deterministic and reversible on MySQL.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    # Engine (InnoDB), charset (utf8mb4) and collation (utf8mb4_0900_ai_ci) come from the
    # database defaults set when it is created, so tables do not repeat them.
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(UUIDBinary, primary_key=True, default=uuid7)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False
    )
