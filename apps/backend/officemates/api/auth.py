"""Auth endpoints: register (local only), login, refresh, logout, /me (BLUEPRINT 5.1).

Sessions live in cookies: a 15-minute JWT access token (HttpOnly), a rotating refresh
token (HttpOnly, sent only to /api/v1/auth) and a CSRF token readable by the web app,
which echoes it in the X-CSRF-Token header on every state-changing request.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from officemates.auth import service
from officemates.auth.dependencies import (
    ACCESS_COOKIE,
    CSRF_COOKIE,
    REFRESH_COOKIE,
    REFRESH_COOKIE_PATH,
    CurrentPrincipal,
    NotAuthenticatedError,
    client_info,
    settings_of,
    signing_key,
)
from officemates.auth.models import RevokeReason
from officemates.auth.passwords import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH
from officemates.auth.tokens import AccessClaims, create_access_token, new_csrf_token
from officemates.core.config import Settings
from officemates.core.errors import AppError, ConflictError, NotFoundError
from officemates.db.session import get_session
from officemates.db.types import utcnow
from officemates.identity.models import Role, Tenant, User

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])
me_router = APIRouter(tags=["auth"])

Session = Annotated[AsyncSession, Depends(get_session)]
Password = Annotated[str, Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)]


class InvalidCredentialsError(AppError):
    status = 401
    code = "invalid-credentials"
    title = "Email or password is incorrect"


class NoMembershipError(AppError):
    status = 403
    code = "no-active-membership"
    title = "Your account is not a member of an active organisation"


# -------------------------------------------------------------------- schemas ----


class RegisterRequest(BaseModel):
    email: EmailStr = Field(max_length=320)
    password: Password
    display_name: str = Field(min_length=1, max_length=200)
    organisation_name: str = Field(min_length=1, max_length=200)


class LoginRequest(BaseModel):
    email: EmailStr = Field(max_length=320)
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)
    organisation: str | None = Field(default=None, max_length=64, description="tenant slug")


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str


class TenantOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str


class MeResponse(BaseModel):
    user: UserOut
    tenant: TenantOut
    role: Role


# -------------------------------------------------------------------- cookies ----


def _set_session_cookies(
    response: Response, request: Request, issued: service.IssuedSession
) -> None:
    settings = settings_of(request)
    access = create_access_token(
        signing_key(request),
        AccessClaims(issued.user_id, issued.tenant_id, issued.family_id),
        minutes=settings.access_token_minutes,
    )
    response.set_cookie(
        ACCESS_COOKIE,
        access,
        max_age=settings.access_token_minutes * 60,
        httponly=True,
        path="/",
        secure=settings.cookie_secure,
        samesite="lax",
    )
    response.set_cookie(
        REFRESH_COOKIE,
        issued.refresh_token,
        max_age=settings.refresh_token_days * 86400,
        httponly=True,
        path=REFRESH_COOKIE_PATH,
        secure=settings.cookie_secure,
        samesite="lax",
    )
    response.set_cookie(
        CSRF_COOKIE,
        new_csrf_token(),
        max_age=settings.refresh_token_days * 86400,
        httponly=False,  # the web app reads it and sends it back as a header
        path="/",
        secure=settings.cookie_secure,
        samesite="lax",
    )


def _clear_session_cookies(response: Response, settings: Settings) -> None:
    for name, path in (
        (ACCESS_COOKIE, "/"),
        (REFRESH_COOKIE, REFRESH_COOKIE_PATH),
        (CSRF_COOKIE, "/"),
    ):
        response.delete_cookie(name, path=path, secure=settings.cookie_secure, samesite="lax")


def _me(user: User, tenant: Tenant, role: Role) -> MeResponse:
    return MeResponse(
        user=UserOut(id=user.id, email=user.email, display_name=user.display_name),
        tenant=TenantOut(id=tenant.id, name=tenant.name, slug=tenant.slug),
        role=role,
    )


def _lifetime(request: Request) -> timedelta:
    return timedelta(days=settings_of(request).refresh_token_days)


# ------------------------------------------------------------------ endpoints ----


@router.post("/register", status_code=status.HTTP_201_CREATED, response_model=MeResponse)
async def register(
    body: RegisterRequest, request: Request, response: Response, session: Session
) -> MeResponse:
    """Create an organisation and its owner. Local development only."""
    if not settings_of(request).allow_registration:
        raise NotFoundError
    client = client_info(request)
    try:
        tenant, user = await service.register_owner(
            session,
            email=body.email,
            password=body.password,
            display_name=body.display_name,
            tenant_name=body.organisation_name,
        )
    except IntegrityError as exc:
        raise ConflictError(detail="an account with this email already exists") from exc
    issued = await service.issue_session(
        session, user_id=user.id, tenant_id=tenant.id, lifetime=_lifetime(request), client=client
    )
    await service.record_audit(
        session, tenant_id=tenant.id, action="auth.register", actor_user_id=user.id, client=client
    )
    await session.commit()
    _set_session_cookies(response, request, issued)
    return _me(user, tenant, Role.OWNER)


@router.post("/login", response_model=MeResponse)
async def login(
    body: LoginRequest, request: Request, response: Response, session: Session
) -> MeResponse:
    client = client_info(request)
    user = await service.authenticate(session, body.email, body.password)
    if user is None:
        log.warning("auth.login_failed", reason="credentials")
        raise InvalidCredentialsError
    found = await service.active_membership(session, user.id, body.organisation)
    if found is None:
        log.warning("auth.login_failed", reason="no_membership", user_id=str(user.id))
        raise NoMembershipError
    tenant, membership = found
    user.last_login_at = utcnow()
    issued = await service.issue_session(
        session, user_id=user.id, tenant_id=tenant.id, lifetime=_lifetime(request), client=client
    )
    await service.record_audit(
        session, tenant_id=tenant.id, action="auth.login", actor_user_id=user.id, client=client
    )
    await session.commit()
    _set_session_cookies(response, request, issued)
    return _me(user, tenant, Role(membership.role))


@router.post("/refresh", status_code=status.HTTP_204_NO_CONTENT)
async def refresh(request: Request, response: Response, session: Session) -> None:
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise NotAuthenticatedError
    client = client_info(request)
    try:
        issued = await service.rotate_session(
            session, token, lifetime=_lifetime(request), client=client
        )
    except service.RefreshReuseError as exc:
        await service.record_audit(
            session,
            tenant_id=exc.tenant_id,
            action="auth.refresh_reuse_detected",
            actor_user_id=exc.user_id,
            client=client,
            details={"session_id": str(exc.family_id)},
        )
        await session.commit()  # keep the family revocation
        log.warning("auth.refresh_reuse_detected", user_id=str(exc.user_id))
        raise NotAuthenticatedError(detail="session ended") from exc
    except service.RefreshRejectedError as exc:
        await session.commit()
        raise NotAuthenticatedError(detail="session expired") from exc
    await session.commit()
    _set_session_cookies(response, request, issued)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, session: Session) -> Response:
    """Ends the session identified by the refresh cookie. Always clears the cookies."""
    token = request.cookies.get(REFRESH_COOKIE)
    row = await service.family_of(session, token) if token else None
    if row is not None:
        await service.revoke_family(session, row.family_id, RevokeReason.LOGOUT)
        await service.record_audit(
            session,
            tenant_id=row.session_tenant_id,
            action="auth.logout",
            actor_user_id=row.user_id,
            client=client_info(request),
        )
        await session.commit()
    result = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_session_cookies(result, settings_of(request))
    return result


@me_router.get("/me", response_model=MeResponse)
async def me(principal: CurrentPrincipal) -> MeResponse:
    return MeResponse(
        user=UserOut(
            id=principal.user_id, email=principal.email, display_name=principal.display_name
        ),
        tenant=TenantOut(
            id=principal.tenant_id, name=principal.tenant_name, slug=principal.tenant_slug
        ),
        role=principal.role,
    )
