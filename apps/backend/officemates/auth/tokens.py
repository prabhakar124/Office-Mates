"""Access tokens (short-lived JWT) and refresh tokens (opaque, stored hashed)."""

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

import jwt

from officemates.db.types import utcnow

ISSUER = "officemates"
AUDIENCE = "officemates-api"
ALGORITHM = "HS256"


class InvalidTokenError(Exception):
    """Missing, malformed, expired or wrongly signed token."""


@dataclass(frozen=True, slots=True)
class AccessClaims:
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    session_id: uuid.UUID  # the refresh-token family, so logout can end this session


def create_access_token(
    key: str, claims: AccessClaims, *, minutes: int, now: datetime | None = None
) -> str:
    issued = now or utcnow()
    payload = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": str(claims.user_id),
        "tid": str(claims.tenant_id),
        "sid": str(claims.session_id),
        "iat": issued,
        "exp": issued + timedelta(minutes=minutes),
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(payload, key, algorithm=ALGORITHM)


def decode_access_token(key: str, token: str) -> AccessClaims:
    try:
        payload = jwt.decode(
            token,
            key,
            algorithms=[ALGORITHM],  # never trust the header's alg
            audience=AUDIENCE,
            issuer=ISSUER,
            options={"require": ["exp", "iat", "sub", "tid", "sid"]},
        )
        return AccessClaims(
            user_id=uuid.UUID(payload["sub"]),
            tenant_id=uuid.UUID(payload["tid"]),
            session_id=uuid.UUID(payload["sid"]),
        )
    except (jwt.PyJWTError, ValueError, KeyError, TypeError) as exc:
        raise InvalidTokenError from exc


def new_refresh_token() -> tuple[str, str]:
    """Return ``(token for the cookie, hash for the database)``."""
    token = secrets.token_urlsafe(32)
    return token, hash_refresh_token(token)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def hash_ip(key: str, ip: str | None) -> str | None:
    """Keyed hash so stored IPs can be compared but not reversed or looked up."""
    if not ip:
        return None
    return hmac.new(key.encode(), ip.encode(), hashlib.sha256).hexdigest()
