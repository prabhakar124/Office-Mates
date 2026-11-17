"""Audit log rows.

Append-only: database triggers (migration 0002) reject every UPDATE and DELETE, so the
application cannot rewrite history. Retention purges and tenant deletion will need a
migrator-account job that can lift the triggers (not built yet).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from officemates.db.base import Base, UUIDPrimaryKeyMixin
from officemates.db.tenancy import TenantScopedMixin
from officemates.db.types import UTCDateTime, UUIDBinary, utcnow


class AuditLog(UUIDPrimaryKeyMixin, TenantScopedMixin, Base):
    __tablename__ = "audit_logs"
    __tenant_table_args__ = (
        Index(None, "tenant_id", "created_at"),
        Index(None, "tenant_id", "action"),
    )

    # SET NULL keeps the history when a user is deleted; the row still says what happened.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDBinary, ForeignKey("users.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)  # e.g. auth.login
    target_type: Mapped[str | None] = mapped_column(String(32))
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUIDBinary)
    request_id: Mapped[str | None] = mapped_column(String(64))
    ip_hash: Mapped[str | None] = mapped_column(String(64))  # never the raw IP
    user_agent: Mapped[str | None] = mapped_column(String(255))
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
