import pytest
from pydantic import SecretStr

from officemates.core.config import Settings
from officemates.core.redis import with_db
from officemates.workers.celery_app import create_celery
from officemates.workers.tasks import ping


@pytest.mark.parametrize(
    ("url", "db", "expected"),
    [
        ("redis://redis:6379", 1, "redis://redis:6379/1"),
        ("redis://redis:6379/0", 1, "redis://redis:6379/1"),
        ("redis://:pw@redis:6379/5", 0, "redis://:pw@redis:6379/0"),
        (
            "rediss://redis:6380/0?ssl_cert_reqs=required",
            1,
            "rediss://redis:6380/1?ssl_cert_reqs=required",
        ),
    ],
)
def test_with_db(url: str, db: int, expected: str) -> None:
    assert with_db(url, db) == expected


def test_celery_uses_separate_dbs_and_json_only() -> None:
    settings = Settings(_env_file=None, redis_url=SecretStr("redis://example:6379/0"))
    app = create_celery(settings)
    assert app.conf.broker_url == "redis://example:6379/0"
    assert app.conf.result_backend == "redis://example:6379/1"
    assert app.conf.accept_content == ["json"]
    assert app.conf.task_acks_late is True


def test_ping_task_runs_locally() -> None:
    # .apply() runs the task in-process: no broker needed.
    assert ping.apply().get() == "pong"
