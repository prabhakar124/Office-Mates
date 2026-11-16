"""Celery application for background jobs.

Run a worker with:  celery -A officemates.workers.celery_app worker --loglevel=INFO
Real tasks (ingestion, reports, evals) arrive from Phase 2; for now there is one
``system.ping`` task that proves the broker and worker are wired together.
"""

from celery import Celery
from celery.signals import setup_logging

from officemates.core.config import Settings, get_settings
from officemates.core.logging import configure_logging
from officemates.core.redis import with_db

DEFAULT_REDIS_URL = "redis://localhost:6379/0"


def create_celery(settings: Settings | None = None) -> Celery:
    settings = settings or get_settings()
    redis_url = settings.redis_url.get_secret_value() if settings.redis_url else DEFAULT_REDIS_URL

    app = Celery(
        "officemates",
        broker=with_db(redis_url, 0),
        backend=with_db(redis_url, 1),
        include=["officemates.workers.tasks"],
    )
    app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],  # never unpickle data from the broker
        timezone="UTC",
        enable_utc=True,
        task_acks_late=True,  # re-deliver if a worker dies mid-task (tasks must be idempotent)
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        task_time_limit=600,
        task_soft_time_limit=540,
        result_expires=3600,
        broker_connection_retry_on_startup=True,
        task_default_queue="default",
    )
    return app


@setup_logging.connect
def _configure_worker_logging(**_: object) -> None:
    """Use the same structured logging as the API instead of Celery's default."""
    settings = get_settings()
    configure_logging(settings.log_level, json=settings.log_json)


celery_app = create_celery()
