"""Identity models.

``tenants`` and ``users`` are platform-level (a user can belong to several tenants);
``memberships`` is tenant-scoped and carries the user's role in that tenant.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, Boolean, CheckConstraint, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from officemates.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from officemates.db.tenancy import TenantScopedMixin
from officemates.db.types import UTCDateTime, UUIDBinary


def _in(column: str, values: type[StrEnum]) -> str:
    return f"`{column}` IN ({', '.join(repr(v.value) for v in values)})"


class TenantStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


class TenantPlan(StrEnum):
    STANDARD = "standard"


class UserStatus(StrEnum):
    ACTIVE = "active"
    INVITED = "invited"  # invitation sent, password not set yet
    DISABLED = "disabled"


class Role(StrEnum):
    """Tenant roles, most to least privileged. Permissions per role live in auth."""

    OWNER = "owner"
    ADMIN = "admin"
    EDITOR = "editor"
    MEMBER = "member"
    VIEWER = "viewer"


class MembershipStatus(StrEnum):
    ACTIVE = "active"
    REMOVED = "removed"


class Tenant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tenants"
    __table_args__ = (
        CheckConstraint(_in("status", TenantStatus), name="status"),
        CheckConstraint(_in("plan", TenantPlan), name="plan"),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    plan: Mapped[str] = mapped_column(String(32), nullable=False, default=TenantPlan.STANDARD)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=TenantStatus.ACTIVE)
    # Set when the tenant's vector namespace is created (ADR 003): t_{tenant_id hex}.
    pinecone_namespace: Mapped[str | None] = mapped_column(String(64), unique=True)
    # Data-protection toggles etc.; validated by Pydantic before writing.
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint(_in("status", UserStatus), name="status"),)

    # utf8mb4_0900_ai_ci is case-insensitive, so the unique key also rejects case variants.
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))  # Argon2id; None = no password
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=UserStatus.ACTIVE)
    email_verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Membership(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "memberships"
    __tenant_table_args__ = (
        UniqueConstraint("tenant_id", "user_id"),
        Index(None, "user_id"),  # "which tenants is this user in" at login
        CheckConstraint(_in("role", Role), name="role"),
        CheckConstraint(_in("status", MembershipStatus), name="status"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDBinary, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=MembershipStatus.ACTIVE)
