"""FastAPI application factory.

``create_app()`` builds a fresh app (tests create their own with custom settings);
``app`` is the module-level instance used by uvicorn: ``uvicorn officemates.main:app``.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from officemates import __version__
from officemates.api import health
from officemates.core.config import Settings, get_settings
from officemates.core.errors import register_error_handlers
from officemates.core.health import ReadinessRegistry
from officemates.core.logging import configure_logging
from officemates.core.middleware import RequestContextMiddleware, SecurityHeadersMiddleware

API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json=settings.log_json)

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        docs_url="/docs" if settings.show_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.show_docs else None,
    )
    app.state.settings = settings
    app.state.readiness = ReadinessRegistry()

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

    # Platform endpoints live at the root (load balancers and probes expect that);
    # feature routers will be mounted under API_PREFIX from Phase 1.
    app.include_router(health.router)

    return app


app = create_app()
