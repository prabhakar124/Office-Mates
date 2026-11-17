import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from officemates.core.config import Environment, Settings
from officemates.main import create_app


def test_generates_request_id(client: TestClient) -> None:
    resp = client.get("/healthz")
    rid = resp.headers["x-request-id"]
    assert len(rid) == 32
    assert rid != client.get("/healthz").headers["x-request-id"]


def test_accepts_safe_incoming_request_id(client: TestClient) -> None:
    resp = client.get("/healthz", headers={"X-Request-ID": "abc-123_XYZ.789"})
    assert resp.headers["x-request-id"] == "abc-123_XYZ.789"


@pytest.mark.parametrize(
    "bad",
    ["short", "a" * 65, "abc 12345 def", "abc\\n12345", "<script>alert(1)</script>"],
)
def test_rejects_unsafe_incoming_request_id(client: TestClient, bad: str) -> None:
    resp = client.get("/healthz", headers={"X-Request-ID": bad})
    assert resp.headers["x-request-id"] != bad
    assert len(resp.headers["x-request-id"]) == 32


def test_security_headers(client: TestClient) -> None:
    resp = client.get("/healthz")
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["referrer-policy"] == "no-referrer"
    assert "strict-transport-security" not in resp.headers  # only when deployed behind TLS


def test_hsts_and_no_docs_when_deployed() -> None:
    settings = Settings(
        _env_file=None, environment=Environment.PROD, jwt_secret=SecretStr("x" * 40)
    )
    with TestClient(create_app(settings)) as c:
        assert "strict-transport-security" in c.get("/healthz").headers
        assert c.get("/docs").status_code == 404
        assert c.get("/openapi.json").status_code == 404


def test_docs_available_locally(client: TestClient) -> None:
    assert client.get("/openapi.json").status_code == 200


def test_cors_allows_only_configured_origin(client: TestClient) -> None:
    allowed = client.get("/healthz", headers={"Origin": "http://localhost:3000"})
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert allowed.headers["access-control-allow-credentials"] == "true"

    denied = client.get("/healthz", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in denied.headers


def test_api_responses_forbid_loading_anything(client: TestClient) -> None:
    csp = client.get("/healthz").headers["content-security-policy"]
    assert "default-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "content-security-policy" not in client.get("/docs").headers
