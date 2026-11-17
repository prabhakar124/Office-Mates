"""Refresh tokens: one row per issued token, grouped into families per login session.

Only a SHA-256 hash of each token is stored. Every refresh revokes the presented token and
issues a successor in the same family. Presenting a token that was already rotated means it
leaked (or a client replayed it), so the whole family is revoked: the attacker and the user
are both signed out and the user logs in again.

Platform-level (not tenant-scoped): a session belongs to a user and records which tenant
is active in ``session_tenant_id``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from officemates.db.base import Base, UUIDPrimaryKeyMixin
from officemates.db.types import UTCDateTime, UUIDBinary, utcnow


class RevokeReason(StrEnum):
    ROTATED = "rotated"
    LOGOUT = "logout"
    REUSE_DETECTED = "reuse_detected"


class RefreshToken(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = (
        Index(None, "family_id"),
        Index(None, "user_id"),
        CheckConstraint(
            "`revoke_reason` IS NULL OR `revoke_reason` IN "
            f"({', '.join(repr(r.value) for r in RevokeReason)})",
            name="revoke_reason",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDBinary, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    session_tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUIDBinary, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    family_id: Mapped[uuid.UUID] = mapped_column(UUIDBinary, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    revoke_reason: Mapped[str | None] = mapped_column(String(32))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
