"""Login, session issue, refresh rotation with reuse detection, logout."""

from __future__ import annotations

import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from officemates.audit.models import AuditLog
from officemates.auth.models import RefreshToken, RevokeReason
from officemates.auth.passwords import hash_password, needs_rehash, verify_password
from officemates.auth.tokens import hash_refresh_token, new_refresh_token
from officemates.core.request_context import get_request_id
from officemates.core.tenancy import system_scope, tenant_scope
from officemates.db.types import utcnow
from officemates.identity.models import (
    Membership,
    MembershipStatus,
    Role,
    Tenant,
    TenantStatus,
    User,
    UserStatus,
)

log = structlog.get_logger(__name__)


class RefreshRejectedError(Exception):
    """The refresh token is unknown, expired or revoked."""


class RefreshReuseError(RefreshRejectedError):
    """An already-rotated token was presented again; its family has been revoked."""

    def __init__(self, user_id: uuid.UUID, tenant_id: uuid.UUID, family_id: uuid.UUID) -> None:
        super().__init__("refresh token reuse")
        self.user_id = user_id
        self.tenant_id = tenant_id
        self.family_id = family_id


@dataclass(frozen=True, slots=True)
class ClientInfo:
    user_agent: str | None
    ip_hash: str | None


@dataclass(frozen=True, slots=True)
class IssuedSession:
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    family_id: uuid.UUID
    refresh_token: str


# ------------------------------------------------------------------- accounts ----


async def authenticate(session: AsyncSession, email: str, password: str) -> User | None:
    user = await session.scalar(select(User).where(User.email == email))
    if not verify_password(user.password_hash if user else None, password) or user is None:
        return None
    if user.status != UserStatus.ACTIVE:
        return None
    if user.password_hash and needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    return user


async def active_membership(
    session: AsyncSession, user_id: uuid.UUID, tenant_slug: str | None = None
) -> tuple[Tenant, Membership] | None:
    """The tenant to sign in to: the requested one, else the user's oldest membership."""
    query = (
        select(Tenant, Membership)
        .join(Membership, Membership.tenant_id == Tenant.id)
        .where(
            Membership.user_id == user_id,
            Membership.status == MembershipStatus.ACTIVE,
            Tenant.status == TenantStatus.ACTIVE,
        )
        .order_by(Membership.created_at, Membership.id)
    )
    if tenant_slug:
        query = query.where(Tenant.slug == tenant_slug)
    # Before sign-in there is no tenant yet: this is the one cross-tenant read login needs.
    with system_scope("auth.resolve_membership"):
        row = (await session.execute(query.limit(1))).first()
    return (row[0], row[1]) if row else None


async def membership_in(
    session: AsyncSession, user_id: uuid.UUID, tenant_id: uuid.UUID
) -> Membership | None:
    with tenant_scope(tenant_id):
        return await session.scalar(
            select(Membership)
            .join(Tenant, Tenant.id == Membership.tenant_id)
            .where(
                Membership.user_id == user_id,
                Membership.status == MembershipStatus.ACTIVE,
                Tenant.status == TenantStatus.ACTIVE,
            )
        )


def slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:48] or "org"
    return f"{base}-{secrets.token_hex(3)}"


async def register_owner(
    session: AsyncSession, *, email: str, password: str, display_name: str, tenant_name: str
) -> tuple[Tenant, User]:
    tenant = Tenant(name=tenant_name, slug=slugify(tenant_name))
    user = User(email=email, password_hash=hash_password(password), display_name=display_name)
    session.add_all([tenant, user])
    await session.flush()
    with tenant_scope(tenant.id):
        session.add(Membership(user_id=user.id, role=Role.OWNER))
        await session.flush()
    return tenant, user


# ------------------------------------------------------------------- sessions ----


async def issue_session(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    lifetime: timedelta,
    client: ClientInfo,
    family_id: uuid.UUID | None = None,
) -> IssuedSession:
    token, token_hash = new_refresh_token()
    family = family_id or uuid.uuid4()
    session.add(
        RefreshToken(
            user_id=user_id,
            session_tenant_id=tenant_id,
            family_id=family,
            token_hash=token_hash,
            expires_at=utcnow() + lifetime,
            user_agent=client.user_agent,
            ip_hash=client.ip_hash,
        )
    )
    await session.flush()
    return IssuedSession(user_id, tenant_id, family, token)


async def rotate_session(
    session: AsyncSession, token: str, *, lifetime: timedelta, client: ClientInfo
) -> IssuedSession:
    """Swap a refresh token for a new one. Reuse of a rotated token revokes the family."""
    row = await session.scalar(
        select(RefreshToken)
        .where(RefreshToken.token_hash == hash_refresh_token(token))
        .with_for_update()  # two concurrent refreshes with one token: the second sees it used
    )
    if row is None or row.expires_at <= utcnow():
        raise RefreshRejectedError("unknown or expired")
    if row.revoked_at is not None:
        if row.revoke_reason == RevokeReason.ROTATED:
            await revoke_family(session, row.family_id, RevokeReason.REUSE_DETECTED)
            raise RefreshReuseError(row.user_id, row.session_tenant_id, row.family_id)
        raise RefreshRejectedError("revoked")

    if await membership_in(session, row.user_id, row.session_tenant_id) is None:
        await revoke_family(session, row.family_id, RevokeReason.LOGOUT)
        raise RefreshRejectedError("membership no longer active")
    user = await session.get(User, row.user_id)
    if user is None or user.status != UserStatus.ACTIVE:
        await revoke_family(session, row.family_id, RevokeReason.LOGOUT)
        raise RefreshRejectedError("user no longer active")

    row.revoked_at = utcnow()
    row.revoke_reason = RevokeReason.ROTATED
    return await issue_session(
        session,
        user_id=row.user_id,
        tenant_id=row.session_tenant_id,
        lifetime=lifetime,
        client=client,
        family_id=row.family_id,
    )


async def revoke_family(session: AsyncSession, family_id: uuid.UUID, reason: RevokeReason) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow(), revoke_reason=reason)
    )


async def session_is_active(session: AsyncSession, family_id: uuid.UUID) -> bool:
    """True while the login session (refresh family) has an unrevoked, unexpired token."""
    found = await session.scalar(
        select(RefreshToken.id).where(
            RefreshToken.family_id == family_id,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > utcnow(),
        )
    )
    return found is not None


async def family_of(session: AsyncSession, token: str) -> RefreshToken | None:
    return await session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(token))
    )


# ---------------------------------------------------------------------- audit ----


async def record_audit(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    action: str,
    actor_user_id: uuid.UUID | None,
    client: ClientInfo,
    target: tuple[str, uuid.UUID] | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    with tenant_scope(tenant_id):
        session.add(
            AuditLog(
                actor_user_id=actor_user_id,
                action=action,
                target_type=target[0] if target else None,
                target_id=target[1] if target else None,
                request_id=get_request_id(),
                ip_hash=client.ip_hash,
                user_agent=client.user_agent,
                details=details or {},
            )
        )
        await session.flush()
    log.info("audit", action=action, tenant_id=str(tenant_id))
