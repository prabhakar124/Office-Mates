"""FastAPI application factory.

``create_app()`` builds a fresh app (tests create their own with custom settings);
``app`` is the module-level instance used by uvicorn: ``uvicorn officemates.main:app``.
"""

import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncEngine

from officemates import __version__
from officemates.api import auth, health
from officemates.auth.dependencies import csrf_protect
from officemates.core.config import Settings, get_settings
from officemates.core.errors import register_error_handlers
from officemates.core.health import ReadinessRegistry
from officemates.core.logging import configure_logging
from officemates.core.middleware import RequestContextMiddleware, SecurityHeadersMiddleware
from officemates.core.redis import redis_readiness_check
from officemates.db.session import (
    create_engine,
    create_session_factory,
    database_readiness_check,
)

API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json=settings.log_json)

    engine: AsyncEngine | None = None
    if settings.database_url is not None:
        engine = create_engine(
            settings.database_url.get_secret_value(), pool_size=settings.database_pool_size
        )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        if engine is not None:
            await engine.dispose()

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        docs_url="/docs" if settings.show_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.show_docs else None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine) if engine is not None else None
    if settings.jwt_secret is not None:
        app.state.auth_signing_key = settings.jwt_secret.get_secret_value()
    else:  # local only (deployed settings refuse to load without a secret)
        app.state.auth_signing_key = secrets.token_urlsafe(48)
        structlog.get_logger(__name__).warning(
            "auth.ephemeral_signing_key", hint="set OM_JWT_SECRET to keep sessions across restarts"
        )
    app.state.readiness = ReadinessRegistry()
    if engine is not None:
        app.state.readiness.register("mysql", database_readiness_check(engine))
    if settings.redis_url is not None:
        app.state.readiness.register(
            "redis", redis_readiness_check(settings.redis_url.get_secret_value())
        )

    register_error_handlers(app)

    # Starlette runs the last-added middleware outermost. Order (outer → inner):
    # CORS → security headers → request context, so even the 500 responses that the request
    # context middleware generates still get security and CORS headers.
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.is_deployed)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
            allow_headers=["Content-Type", "X-CSRF-Token", "X-Request-ID", "Idempotency-Key"],
            expose_headers=["X-Request-ID"],
        )

    # Platform endpoints live at the root (load balancers and probes expect that).
    app.include_router(health.router)
    # Every API route gets the CSRF check; it lets safe methods through.
    api = [Depends(csrf_protect)]
    app.include_router(auth.router, prefix=API_PREFIX, dependencies=api)
    app.include_router(auth.me_router, prefix=API_PREFIX, dependencies=api)

    return app


app = create_app()
