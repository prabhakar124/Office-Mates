"""Fail-closed tenant isolation in the ORM (ADR 002).

MySQL has no row-level security, so isolation is enforced here, on every ORM session:

* ``TenantScopedMixin`` gives a model a ``tenant_id`` column (NOT NULL, foreign key to
  ``tenants``) and a unique ``(tenant_id, id)`` key that child tables reference with
  composite foreign keys (``tenant_foreign_key``), so a row can never point at another
  tenant's row.
* SELECT, UPDATE and DELETE statements that touch a tenant-scoped model get
  ``tenant_id = <current tenant>`` added automatically, including relationship loads.
* New rows are stamped with the current tenant; writing a row for another tenant, or
  changing a row's ``tenant_id``, raises.
* With no tenant and no system scope, any of the above raises ``TenantContextMissingError``.

What this does NOT cover: raw SQL (``text()``) and Core statements on ``Table`` objects.
Those are only allowed in repository code and are reviewed (and later linted) for this.
"""

from __future__ import annotations

import uuid
from typing import Any, cast

from sqlalchemy import ForeignKey, ForeignKeyConstraint, UniqueConstraint, event, inspect
from sqlalchemy.orm import (
    Mapped,
    ORMExecuteState,
    Session,
    UOWTransaction,
    declared_attr,
    mapped_column,
    with_loader_criteria,
)
from sqlalchemy.sql import visitors
from sqlalchemy.sql.expression import FromClause
from sqlalchemy.sql.schema import Column, Table

from officemates.core.tenancy import current_tenant_id, system_scope_reason
from officemates.db.base import Base
from officemates.db.types import UUIDBinary


class TenantIsolationError(RuntimeError):
    """A programming error that would break tenant isolation.

    Deliberately not an ``AppError``: clients get a generic 500 and the details go to the
    logs only.
    """


class TenantContextMissingError(TenantIsolationError):
    """A tenant-scoped query or write ran with no tenant and no system scope."""


class CrossTenantWriteError(TenantIsolationError):
    """A write tried to create or move a row into a tenant other than the current one."""


class UnscopedTableAccessError(TenantIsolationError):
    """A tenant table was used as a bare Core ``Table``, where no tenant filter applies."""


class TenantScopedMixin:
    """Base for every model that belongs to one tenant.

    Extra table arguments go in ``__tenant_table_args__`` (a tuple), because this mixin
    owns ``__table_args__``.
    """

    __tenant_table_args__: tuple[Any, ...] = ()

    @declared_attr
    @classmethod
    def tenant_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(
            UUIDBinary, ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False
        )

    @declared_attr.directive
    @classmethod
    def __table_args__(cls) -> tuple[Any, ...]:
        # Leading tenant_id: serves tenant-filtered lookups and is the target of
        # composite foreign keys from child tables.
        return (UniqueConstraint("tenant_id", "id"), *cls.__tenant_table_args__)


def tenant_foreign_key(
    column: str, parent_table: str, *, ondelete: str = "RESTRICT"
) -> ForeignKeyConstraint:
    """Composite FK ``(tenant_id, column) -> parent(tenant_id, id)`` for child tables.

    Use it in ``__tenant_table_args__`` instead of a plain ``ForeignKey`` on ``column``.
    """
    return ForeignKeyConstraint(
        ["tenant_id", column],
        [f"{parent_table}.tenant_id", f"{parent_table}.id"],
        ondelete=ondelete,
    )


def _sets_tenant_id(statement: Any) -> bool:
    # SQLAlchemy keeps an UPDATE's SET clause here (no public accessor); keys are column
    # objects or names. Covered by tests so a library change cannot silently break it.
    values = getattr(statement, "_values", None) or {}
    ordered = getattr(statement, "_ordered_values", None) or ()
    keys = list(values) + [k for k, _ in ordered]
    return any(getattr(k, "key", getattr(k, "name", k)) == "tenant_id" for k in keys)


def _tenant_tables() -> set[FromClause]:
    return {m.local_table for m in Base.registry.mappers if issubclass(m.class_, TenantScopedMixin)}


def _inspect_statement(state: ORMExecuteState) -> tuple[bool, bool]:
    """Return ``(touches_tenant_data, uses_bare_tenant_table)``.

    ``all_mappers`` lists only the selected entities, so the whole statement is walked:
    a tenant table that is joined, aliased or used in a subquery, CTE or UNION counts too.
    "Bare" means referenced as a Core ``Table``/``Column`` instead of through its ORM
    entity; the tenant filter can only be attached to ORM entities.
    """
    scoped = _tenant_tables()
    touches = any(issubclass(m.class_, TenantScopedMixin) for m in state.all_mappers)
    via_entity: set[Any] = set()  # tenant tables the statement reaches through ORM entities
    bare_columns: set[Any] = set()  # tenant tables referenced by plain Core columns
    for element in visitors.iterate(cast("visitors.ExternallyTraversible", state.statement)):
        if not isinstance(element, (Table, Column)):
            continue
        entity = element._annotations.get("parententity")
        if entity is not None:
            table = entity.mapper.local_table
            if table in scoped:
                touches = True
                via_entity.add(table)
        elif isinstance(element, Column) and element.table in scoped:
            touches = True
            bare_columns.add(element.table)
        elif isinstance(element, Table) and element in scoped:
            touches = True  # an ORM column's children include its plain Table
    # A plain column is harmless when its table is also an ORM entity of the statement
    # (session.get() builds its WHERE that way): the entity carries the tenant filter.
    bare = bool(bare_columns - via_entity)
    target = getattr(state.statement, "table", None)  # UPDATE / DELETE target
    if isinstance(target, Table) and target in scoped:
        touches = True
        bare = bare or "parententity" not in target._annotations
    return touches, bare


@event.listens_for(Session, "do_orm_execute")
def _scope_statements(state: ORMExecuteState) -> None:
    if not (state.is_select or state.is_update or state.is_delete):
        return
    touches, bare = _inspect_statement(state)
    if not touches:
        return
    if state.is_update and _sets_tenant_id(state.statement):
        # Bulk UPDATE skips the flush guard below, so moving rows between tenants this
        # way is refused outright, even in a system scope.
        raise CrossTenantWriteError("tenant_id cannot be changed")
    if system_scope_reason() is not None:
        return
    tenant_id = current_tenant_id()
    if tenant_id is None:
        raise TenantContextMissingError("query on tenant-scoped data without a tenant scope")
    if bare:
        raise UnscopedTableAccessError(
            "tenant tables must be queried through their ORM model, not the Core Table"
        )
    state.statement = state.statement.options(
        with_loader_criteria(
            TenantScopedMixin,
            lambda cls: cls.tenant_id == tenant_id,
            include_aliases=True,
        )
    )


@event.listens_for(Session, "before_flush")
def _guard_writes(session: Session, _flush: UOWTransaction, _instances: object) -> None:
    system = system_scope_reason() is not None
    tenant_id = current_tenant_id()

    for obj in session.new:
        if not isinstance(obj, TenantScopedMixin):
            continue
        if system:
            if obj.tenant_id is None:
                raise CrossTenantWriteError("system scope writes must set tenant_id")
            continue
        if tenant_id is None:
            raise TenantContextMissingError("insert of tenant-scoped row without scope")
        if obj.tenant_id is None:
            obj.tenant_id = tenant_id
        elif obj.tenant_id != tenant_id:
            raise CrossTenantWriteError("insert into another tenant")

    for obj in session.dirty:
        if isinstance(obj, TenantScopedMixin) and inspect(obj).attrs.tenant_id.history.deleted:
            raise CrossTenantWriteError("tenant_id cannot be changed")

    if not system and tenant_id is None:
        for obj in session.deleted:
            if isinstance(obj, TenantScopedMixin):
                raise TenantContextMissingError("delete of tenant-scoped row without scope")
