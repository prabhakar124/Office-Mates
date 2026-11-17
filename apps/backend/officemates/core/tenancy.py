"""The tenant a unit of work runs as (ADR 002).

The API sets the tenant from the authenticated session, never from request input:

    with tenant_scope(principal.tenant_id):
        ...  # every ORM query on a tenant-scoped model is filtered to this tenant

Platform code that must cross tenants (migrations, tenant deletion, login before a
tenant is chosen) uses an explicit, logged escape hatch:

    with system_scope("auth.resolve_memberships"):
        ...

With neither active, queries on tenant-scoped models raise instead of returning
everything: forgetting the scope fails closed.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

import structlog

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class _Scope:
    tenant_id: uuid.UUID | None = None
    system_reason: str | None = None


_scope: ContextVar[_Scope] = ContextVar("tenant_scope", default=_Scope())  # noqa: B039 - immutable


def current_tenant_id() -> uuid.UUID | None:
    return _scope.get().tenant_id


def system_scope_reason() -> str | None:
    """Why the current code runs across tenants, or ``None`` outside a system scope."""
    return _scope.get().system_reason


@contextmanager
def tenant_scope(tenant_id: uuid.UUID) -> Iterator[None]:
    """Run as ``tenant_id``. Leaves any enclosing system scope for the duration."""
    if not isinstance(tenant_id, uuid.UUID):
        raise TypeError(f"tenant_id must be uuid.UUID, got {type(tenant_id).__name__}")
    token = _scope.set(_Scope(tenant_id=tenant_id))
    try:
        yield
    finally:
        _scope.reset(token)


@contextmanager
def system_scope(reason: str) -> Iterator[None]:
    """Run across all tenants. ``reason`` is a short stable label and is always logged."""
    if not reason.strip():
        raise ValueError("system_scope needs a reason")
    log.info("tenancy.system_scope", reason=reason)
    token = _scope.set(_Scope(system_reason=reason))
    try:
        yield
    finally:
        _scope.reset(token)
