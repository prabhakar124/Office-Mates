"""Token and password primitives (no database)."""

import base64
import json
import uuid
from datetime import timedelta

import pytest

from officemates.auth.passwords import hash_password, needs_rehash, verify_password
from officemates.auth.tokens import (
    AccessClaims,
    InvalidTokenError,
    create_access_token,
    decode_access_token,
    hash_ip,
    hash_refresh_token,
    new_refresh_token,
)
from officemates.db.types import utcnow

KEY = "k" * 48
CLAIMS = AccessClaims(uuid.uuid4(), uuid.uuid4(), uuid.uuid4())


def test_access_token_round_trip() -> None:
    assert decode_access_token(KEY, create_access_token(KEY, CLAIMS, minutes=15)) == CLAIMS


def test_wrong_key_rejected() -> None:
    token = create_access_token(KEY, CLAIMS, minutes=15)
    with pytest.raises(InvalidTokenError):
        decode_access_token("x" * 48, token)


def test_expired_token_rejected() -> None:
    token = create_access_token(KEY, CLAIMS, minutes=15, now=utcnow() - timedelta(minutes=16))
    with pytest.raises(InvalidTokenError):
        decode_access_token(KEY, token)


def _b64(data: dict[str, object]) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()


def test_unsigned_alg_none_token_rejected() -> None:
    header = _b64({"alg": "none", "typ": "JWT"})
    payload = _b64({"sub": str(CLAIMS.user_id), "tid": str(CLAIMS.tenant_id)})
    with pytest.raises(InvalidTokenError):
        decode_access_token(KEY, f"{header}.{payload}.")


def test_tampered_tenant_claim_rejected() -> None:
    header, _, signature = create_access_token(KEY, CLAIMS, minutes=15).split(".")
    forged = _b64({"sub": str(CLAIMS.user_id), "tid": str(uuid.uuid4()), "sid": "x"})
    with pytest.raises(InvalidTokenError):
        decode_access_token(KEY, f"{header}.{forged}.{signature}")


@pytest.mark.parametrize("garbage", ["", "abc", "a.b.c"])
def test_garbage_rejected(garbage: str) -> None:
    with pytest.raises(InvalidTokenError):
        decode_access_token(KEY, garbage)


def test_refresh_tokens_are_random_and_stored_hashed() -> None:
    (t1, h1), (t2, _) = new_refresh_token(), new_refresh_token()
    assert t1 != t2
    assert h1 == hash_refresh_token(t1)
    assert t1 not in h1


def test_ip_hash_is_keyed() -> None:
    assert hash_ip(KEY, "203.0.113.7") != hash_ip("y" * 48, "203.0.113.7")
    assert hash_ip(KEY, None) is None


def test_password_hashing() -> None:
    stored = hash_password("correct horse battery")
    assert stored.startswith("$argon2id$")
    assert verify_password(stored, "correct horse battery")
    assert not verify_password(stored, "wrong horse battery")
    assert not needs_rehash(stored)


def test_missing_hash_never_verifies() -> None:
    assert not verify_password(None, "office-mates-timing-equaliser")
    assert not verify_password("not-a-hash", "anything")
