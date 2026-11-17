"""Auth endpoints end to end against the real MySQL (BLUEPRINT 5.1, D10)."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select

from officemates.audit.models import AuditLog
from officemates.auth.models import RefreshToken, RevokeReason
from officemates.core.config import Environment, Settings
from officemates.core.tenancy import current_tenant_id, system_scope
from officemates.db.session import create_engine, create_session_factory
from officemates.identity.models import Membership, Role, Tenant, User
from officemates.main import create_app
from tests.integration.conftest import DbUrls

pytestmark = pytest.mark.integration

API = "/api/v1"
PASSWORD = "a-long-enough-password"  # noqa: S105 - test-only password


def _settings(urls: DbUrls, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "_env_file": None,
        "environment": Environment.TEST,
        "database_url": SecretStr(urls.app),
        "jwt_secret": SecretStr("test-signing-key-" + "x" * 32),
        **overrides,
    }
    return Settings(**values)


@pytest.fixture
def client(migrated_db: DbUrls) -> Iterator[TestClient]:
    with TestClient(create_app(_settings(migrated_db))) as c:
        yield c


def _email() -> str:
    return f"user-{uuid.uuid4().hex[:10]}@example.com"


def register(client: TestClient, email: str | None = None, org: str = "Acme") -> dict[str, Any]:
    resp = client.post(
        f"{API}/auth/register",
        json={
            "email": email or _email(),
            "password": PASSWORD,
            "display_name": "Test User",
            "organisation_name": org,
        },
    )
    assert resp.status_code == 201, resp.text
    body: dict[str, Any] = resp.json()
    return body


def csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies.get("om_csrf") or ""}


def db_rows(urls: DbUrls, statement: Any) -> list[Any]:
    async def run() -> list[Any]:
        engine = create_engine(urls.app, pool_size=1, max_overflow=0)
        try:
            async with create_session_factory(engine)() as session:
                with system_scope("test.inspect"):
                    return list((await session.scalars(statement)).all())
        finally:
            await engine.dispose()

    return asyncio.run(run())


# ------------------------------------------------------------- registration ----


def test_register_creates_owner_and_signs_in(client: TestClient) -> None:
    body = register(client, org="Acme Office")
    assert body["role"] == "owner"
    assert body["tenant"]["slug"].startswith("acme-office-")

    cookies = {c.name: c for c in client.cookies.jar}
    assert cookies["om_access"].has_nonstandard_attr("HttpOnly")
    assert cookies["om_refresh"].has_nonstandard_attr("HttpOnly")
    assert cookies["om_refresh"].path == "/api/v1/auth"
    assert not cookies["om_csrf"].has_nonstandard_attr("HttpOnly")

    me = client.get(f"{API}/me")
    assert me.status_code == 200
    assert me.json() == body


def test_register_rejects_duplicate_email_in_any_case(client: TestClient) -> None:
    email = _email()
    register(client, email)
    resp = client.post(
        f"{API}/auth/register",
        json={
            "email": email.upper(),
            "password": PASSWORD,
            "display_name": "Copy",
            "organisation_name": "Copy Inc",
        },
    )
    assert resp.status_code == 409


def test_register_disabled_unless_allowed(migrated_db: DbUrls) -> None:
    app = create_app(_settings(migrated_db, allow_registration=False))
    with TestClient(app) as c:
        resp = c.post(
            f"{API}/auth/register",
            json={
                "email": _email(),
                "password": PASSWORD,
                "display_name": "X",
                "organisation_name": "X",
            },
        )
    assert resp.status_code == 404


def test_short_password_rejected(client: TestClient) -> None:
    resp = client.post(
        f"{API}/auth/register",
        json={
            "email": _email(),
            "password": "short",
            "display_name": "X",
            "organisation_name": "X",
        },
    )
    assert resp.status_code == 422


# -------------------------------------------------------------------- login ----


def test_login_and_failures_look_the_same(client: TestClient) -> None:
    email = _email()
    register(client, email)
    client.cookies.clear()

    wrong_password = client.post(f"{API}/auth/login", json={"email": email, "password": "nope"})
    unknown_email = client.post(f"{API}/auth/login", json={"email": _email(), "password": "nope"})
    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json()["title"] == unknown_email.json()["title"]
    assert "om_access" not in client.cookies

    ok = client.post(f"{API}/auth/login", json={"email": email, "password": PASSWORD})
    assert ok.status_code == 200
    assert client.get(f"{API}/me").json()["user"]["email"] == email


def test_login_picks_the_requested_organisation(migrated_db: DbUrls, client: TestClient) -> None:
    email = _email()
    first = register(client, email, org="First")
    second_tenant = uuid.uuid4()

    async def add_second_membership() -> None:
        engine = create_engine(migrated_db.app, pool_size=1, max_overflow=0)
        try:
            async with create_session_factory(engine)() as session:
                with system_scope("test.seed"):
                    session.add(
                        Tenant(
                            id=second_tenant, name="Second", slug=f"second-{uuid.uuid4().hex[:6]}"
                        )
                    )
                    await session.flush()
                    session.add(
                        Membership(
                            tenant_id=second_tenant,
                            user_id=uuid.UUID(first["user"]["id"]),
                            role=Role.VIEWER,
                        )
                    )
                    await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(add_second_membership())
    slug = db_rows(migrated_db, select(Tenant.slug).where(Tenant.id == second_tenant))[0]

    client.cookies.clear()
    default = client.post(f"{API}/auth/login", json={"email": email, "password": PASSWORD})
    assert default.json()["tenant"]["id"] == first["tenant"]["id"]  # oldest membership

    chosen = client.post(
        f"{API}/auth/login", json={"email": email, "password": PASSWORD, "organisation": slug}
    )
    assert chosen.json()["tenant"]["id"] == str(second_tenant)
    assert chosen.json()["role"] == "viewer"


def test_login_is_audited_in_the_right_tenant(migrated_db: DbUrls, client: TestClient) -> None:
    body = register(client)
    actions = db_rows(
        migrated_db,
        select(AuditLog.action).where(
            AuditLog.tenant_id == uuid.UUID(body["tenant"]["id"]),
            AuditLog.actor_user_id == uuid.UUID(body["user"]["id"]),
        ),
    )
    assert actions == ["auth.register"]


def test_login_requires_json(client: TestClient) -> None:
    resp = client.post(f"{API}/auth/login", data={"email": "a@example.com", "password": "x"})
    assert resp.status_code == 403
    assert resp.json()["type"].endswith("csrf-failed")


# --------------------------------------------------------------------- CSRF ----


def test_state_changing_requests_need_the_csrf_header(client: TestClient) -> None:
    register(client)
    assert client.post(f"{API}/auth/logout").status_code == 403
    assert client.post(f"{API}/auth/logout", headers={"X-CSRF-Token": "forged"}).status_code == 403
    assert client.post(f"{API}/auth/logout", headers=csrf(client)).status_code == 204


# ------------------------------------------------------------ refresh & reuse ----


def test_refresh_rotates_the_token(client: TestClient) -> None:
    register(client)
    before = client.cookies.get("om_refresh", path="/api/v1/auth")
    resp = client.post(f"{API}/auth/refresh", headers=csrf(client))
    assert resp.status_code == 204
    after = client.cookies.get("om_refresh", path="/api/v1/auth")
    assert after
    assert after != before
    assert client.get(f"{API}/me").status_code == 200


def test_reusing_a_rotated_token_ends_the_whole_session(
    migrated_db: DbUrls, client: TestClient
) -> None:
    body = register(client)
    stolen = client.cookies.get("om_refresh", path="/api/v1/auth")
    assert client.post(f"{API}/auth/refresh", headers=csrf(client)).status_code == 204
    legit = client.cookies.get("om_refresh", path="/api/v1/auth")

    # The attacker replays the old token: rejected, and the family is revoked.
    client.cookies.set("om_refresh", stolen or "", path="/api/v1/auth")
    assert client.post(f"{API}/auth/refresh", headers=csrf(client)).status_code == 401

    # The legitimate (newer) token is now dead too, and so is the access token.
    client.cookies.set("om_refresh", legit or "", path="/api/v1/auth")
    assert client.post(f"{API}/auth/refresh", headers=csrf(client)).status_code == 401
    assert client.get(f"{API}/me").status_code == 401

    reasons = db_rows(
        migrated_db,
        select(RefreshToken.revoke_reason).where(
            RefreshToken.user_id == uuid.UUID(body["user"]["id"])
        ),
    )
    assert RevokeReason.REUSE_DETECTED in reasons
    actions = db_rows(
        migrated_db,
        select(AuditLog.action).where(AuditLog.actor_user_id == uuid.UUID(body["user"]["id"])),
    )
    assert "auth.refresh_reuse_detected" in actions


def test_refresh_without_cookie_is_rejected(client: TestClient) -> None:
    register(client)
    client.cookies.delete("om_refresh", path="/api/v1/auth")
    assert client.post(f"{API}/auth/refresh", headers=csrf(client)).status_code == 401


# ------------------------------------------------------------------- logout ----


def test_logout_kills_the_access_token_too(client: TestClient) -> None:
    register(client)
    access = client.cookies.get("om_access")
    assert client.post(f"{API}/auth/logout", headers=csrf(client)).status_code == 204
    assert "om_access" not in client.cookies
    client.cookies.set("om_access", access or "")  # a copy kept by an attacker
    assert client.get(f"{API}/me").status_code == 401


def test_removed_member_is_signed_out(migrated_db: DbUrls, client: TestClient) -> None:
    body = register(client)

    async def remove() -> None:
        engine = create_engine(migrated_db.app, pool_size=1, max_overflow=0)
        try:
            async with create_session_factory(engine)() as session:
                with system_scope("test.remove"):
                    membership = await session.scalar(
                        select(Membership).where(
                            Membership.user_id == uuid.UUID(body["user"]["id"])
                        )
                    )
                    assert membership is not None
                    membership.status = "removed"
                    await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(remove())
    assert client.get(f"{API}/me").status_code == 401
    assert client.post(f"{API}/auth/refresh", headers=csrf(client)).status_code == 401


# --------------------------------------------------------------- isolation ----


def test_request_tenant_does_not_leak_out_of_the_request(client: TestClient) -> None:
    register(client)
    assert client.get(f"{API}/me").status_code == 200
    assert current_tenant_id() is None


def test_me_without_session(client: TestClient) -> None:
    resp = client.get(f"{API}/me")
    assert resp.status_code == 401
    assert resp.headers["content-type"].startswith("application/problem+json")


def test_disabled_user_cannot_sign_in(migrated_db: DbUrls, client: TestClient) -> None:
    email = _email()
    register(client, email)

    async def disable() -> None:
        engine = create_engine(migrated_db.app, pool_size=1, max_overflow=0)
        try:
            async with create_session_factory(engine)() as session:
                user = await session.scalar(select(User).where(User.email == email))
                assert user is not None
                user.status = "disabled"
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(disable())
    assert client.get(f"{API}/me").status_code == 401
    client.cookies.clear()
    resp = client.post(f"{API}/auth/login", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 401
