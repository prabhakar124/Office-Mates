from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from officemates.core.config import Environment, Settings
from officemates.main import create_app


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,  # tests must not read a developer's .env
        environment=Environment.TEST,
        git_sha="testsha",
        log_json=True,
        cors_origins=["http://localhost:3000"],
    )


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c
