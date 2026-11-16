"""Background tasks. Only a connectivity check exists until Phase 2."""

from officemates.workers.celery_app import celery_app


@celery_app.task(name="system.ping")
def ping() -> str:
    return "pong"
