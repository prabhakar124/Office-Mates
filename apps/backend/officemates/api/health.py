"""Liveness, readiness and version endpoints (unauthenticated, no sensitive data)."""

from typing import Literal

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel

from officemates import __version__
from officemates.core.config import Settings
from officemates.core.health import ReadinessRegistry

router = APIRouter(tags=["platform"])


class LivenessResponse(BaseModel):
    status: Literal["ok"] = "ok"


class CheckOut(BaseModel):
    name: str
    status: Literal["ok", "fail"]
    duration_ms: float
    error: str | None = None


class ReadinessResponse(BaseModel):
    status: Literal["ok", "fail"]
    checks: list[CheckOut]


class VersionResponse(BaseModel):
    name: str
    version: str
    git_sha: str
    environment: str


@router.get("/healthz", response_model=LivenessResponse)
async def healthz() -> LivenessResponse:
    """The process is up. Never touches dependencies."""
    return LivenessResponse()


@router.get(
    "/readyz",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse}},
)
async def readyz(request: Request, response: Response) -> ReadinessResponse:
    """Every registered dependency check passes."""
    registry: ReadinessRegistry = request.app.state.readiness
    results = await registry.run()
    ok = all(r.status == "ok" for r in results)
    if not ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(
        status="ok" if ok else "fail",
        checks=[
            CheckOut(name=r.name, status=r.status, duration_ms=r.duration_ms, error=r.error)
            for r in results
        ],
    )


@router.get("/version", response_model=VersionResponse)
async def version(request: Request) -> VersionResponse:
    settings: Settings = request.app.state.settings
    return VersionResponse(
        name=settings.app_name,
        version=__version__,
        git_sha=settings.git_sha,
        environment=settings.environment.value,
    )
