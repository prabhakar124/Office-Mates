from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from officemates.core.errors import NotFoundError


class Payload(BaseModel):
    name: str
    count: int


def _add_routes(app: FastAPI) -> None:
    @app.get("/_test/not-found")
    async def not_found() -> None:
        raise NotFoundError("Document 123 does not exist")

    @app.get("/_test/boom")
    async def boom() -> None:
        raise RuntimeError("database password is hunter2")

    @app.post("/_test/validate")
    async def validate(payload: Payload) -> Payload:
        return payload


def test_app_error_is_problem_details(app: FastAPI, client: TestClient) -> None:
    _add_routes(app)
    resp = client.get("/_test/not-found")
    assert resp.status_code == 404
    assert resp.headers["content-type"] == "application/problem+json"
    body = resp.json()
    assert body["type"].endswith("/not-found")
    assert body["title"] == "Resource not found"
    assert body["detail"] == "Document 123 does not exist"
    assert body["instance"] == "/_test/not-found"
    assert body["request_id"] == resp.headers["x-request-id"]


def test_unknown_route_is_problem_details(client: TestClient) -> None:
    resp = client.get("/does-not-exist")
    assert resp.status_code == 404
    assert resp.headers["content-type"] == "application/problem+json"
    assert resp.json()["title"] == "Not Found"


def test_unhandled_error_hides_internals_and_keeps_request_id(
    app: FastAPI, client: TestClient
) -> None:
    _add_routes(app)
    resp = client.get("/_test/boom", headers={"X-Request-ID": "trace-abc-12345"})
    assert resp.status_code == 500
    assert resp.headers["content-type"] == "application/problem+json"
    assert resp.headers["x-request-id"] == "trace-abc-12345"
    assert resp.headers["x-content-type-options"] == "nosniff"
    body = resp.json()
    assert body["request_id"] == "trace-abc-12345"
    assert "hunter2" not in resp.text
    assert "RuntimeError" not in resp.text


def test_validation_error_omits_input_values(app: FastAPI, client: TestClient) -> None:
    _add_routes(app)
    resp = client.post("/_test/validate", json={"name": "sk-live-secret", "count": "many"})
    assert resp.status_code == 422
    body = resp.json()
    assert body["type"].endswith("/validation-error")
    assert body["errors"][0]["loc"] == ["body", "count"]
    assert "sk-live-secret" not in resp.text
    assert "many" not in resp.text
