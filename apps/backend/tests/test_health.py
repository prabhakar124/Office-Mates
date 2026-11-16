import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from officemates import __version__
from officemates.core.health import ReadinessRegistry


def test_healthz_ok(client: TestClient) -> None:
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_readyz_ok_with_no_checks(client: TestClient) -> None:
    resp = client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "checks": []}


def test_readyz_reports_each_check(app: FastAPI, client: TestClient) -> None:
    async def ok() -> None:
        return None

    async def broken() -> None:
        raise ConnectionError("mysql://user:secret@db:3306")  # message must not leak

    registry: ReadinessRegistry = app.state.readiness
    registry.register("redis", ok)
    registry.register("mysql", broken)

    resp = client.get("/readyz")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "fail"
    by_name = {c["name"]: c for c in body["checks"]}
    assert by_name["redis"]["status"] == "ok"
    assert by_name["mysql"] == {**by_name["mysql"], "status": "fail", "error": "ConnectionError"}
    assert "secret" not in resp.text


def test_readyz_times_out_slow_checks(app: FastAPI, client: TestClient) -> None:
    async def slow() -> None:
        await asyncio.sleep(1)

    registry: ReadinessRegistry = app.state.readiness
    registry.timeout_s = 0.05
    registry.register("pinecone", slow)

    resp = client.get("/readyz")
    assert resp.status_code == 503
    assert resp.json()["checks"][0]["error"] == "timeout"


def test_registry_rejects_duplicate_names() -> None:
    async def ok() -> None:
        return None

    registry = ReadinessRegistry()
    registry.register("mysql", ok)
    try:
        registry.register("mysql", ok)
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("duplicate registration should fail")


def test_version(client: TestClient) -> None:
    resp = client.get("/version")
    assert resp.status_code == 200
    assert resp.json() == {
        "name": "Office-Mates",
        "version": __version__,
        "git_sha": "testsha",
        "environment": "test",
    }
