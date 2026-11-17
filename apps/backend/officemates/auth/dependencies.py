"""FastAPI dependencies: the signed-in principal, CSRF protection, client info."""

from __future__ import annotations

import hmac
import uuid
from dataclasses import dataclass
from typing import Annotated

import structlog
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from officemates.auth.service import ClientInfo, membership_in, session_is_active
from officemates.auth.tokens import InvalidTokenError, decode_access_token, hash_ip
from officemates.core.config import Settings
from officemates.core.errors import AppError
from officemates.core.tenancy import bind_request_tenant
from officemates.db.session import get_session
from officemates.identity.models import Role, Tenant, User, UserStatus

ACCESS_COOKIE = "om_access"
REFRESH_COOKIE = "om_refresh"
CSRF_COOKIE = "om_csrf"
CSRF_HEADER = "X-CSRF-Token"
REFRESH_COOKIE_PATH = "/api/v1/auth"

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# Endpoints that start a session. They need no CSRF token (there is no session yet) but
# must be JSON, which a cross-site HTML form cannot send without a CORS preflight.
SESSION_START_PATHS = frozenset(
    {"/api/v1/auth/login", "/api/v1/auth/register", "/api/v1/auth/accept-invitation"}
)


class NotAuthenticatedError(AppError):
    status = 401
    code = "not-authenticated"
    title = "Sign in required"


class CsrfError(AppError):
    status = 403
    code = "csrf-failed"
    title = "Missing or invalid CSRF token"


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    session_id: uuid.UUID
    role: Role
    email: str
    display_name: str
    tenant_name: str
    tenant_slug: str


def settings_of(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def signing_key(request: Request) -> str:
    key: str = request.app.state.auth_signing_key
    return key


def client_info(request: Request) -> ClientInfo:
    agent = request.headers.get("user-agent")
    ip = request.client.host if request.client else None
    return ClientInfo(
        user_agent=agent[:255] if agent else None, ip_hash=hash_ip(signing_key(request), ip)
    )


async def csrf_protect(request: Request) -> None:
    """Double-submit check for every state-changing API request."""
    if request.method in SAFE_METHODS:
        return
    if request.url.path in SESSION_START_PATHS:
        if not request.headers.get("content-type", "").startswith("application/json"):
            raise CsrfError(detail="this endpoint only accepts application/json")
        return
    cookie = request.cookies.get(CSRF_COOKIE, "")
    header = request.headers.get(CSRF_HEADER, "")
    if not cookie or not hmac.compare_digest(cookie, header):
        raise CsrfError


async def current_principal(
    request: Request, session: Annotated[AsyncSession, Depends(get_session)]
) -> Principal:
    token = request.cookies.get(ACCESS_COOKIE)
    if not token:
        raise NotAuthenticatedError
    try:
        claims = decode_access_token(signing_key(request), token)
    except InvalidTokenError as exc:
        raise NotAuthenticatedError(detail="session expired or invalid") from exc

    user = await session.get(User, claims.user_id)
    if user is None or user.status != UserStatus.ACTIVE:
        raise NotAuthenticatedError
    # Logout and reuse detection revoke the session; access tokens die with it.
    if not await session_is_active(session, claims.session_id):
        raise NotAuthenticatedError(detail="session ended")
    membership = await membership_in(session, claims.user_id, claims.tenant_id)
    if membership is None:
        raise NotAuthenticatedError(detail="no active membership in this organisation")
    tenant = await session.get(Tenant, claims.tenant_id)
    if tenant is None:  # cannot happen: membership_in joined an active tenant
        raise NotAuthenticatedError

    bind_request_tenant(claims.tenant_id)  # every query in this request is now scoped
    structlog.contextvars.bind_contextvars(
        tenant_id=str(claims.tenant_id), user_id=str(claims.user_id)
    )
    return Principal(
        user_id=user.id,
        tenant_id=tenant.id,
        session_id=claims.session_id,
        role=Role(membership.role),
        email=user.email,
        display_name=user.display_name,
        tenant_name=tenant.name,
        tenant_slug=tenant.slug,
    )


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]
