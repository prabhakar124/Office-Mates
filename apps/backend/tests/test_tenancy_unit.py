"""Tenant-scope rules and schema guards that need no database (ADR 002)."""

import asyncio
import uuid
from typing import cast

import pytest
from sqlalchemy import ForeignKeyConstraint, Table, UniqueConstraint

from officemates.core.tenancy import (
    current_tenant_id,
    system_scope,
    system_scope_reason,
    tenant_scope,
)
from officemates.db.models import Base
from officemates.db.tenancy import TenantScopedMixin


def tenant_scoped_tables() -> dict[str, type[TenantScopedMixin]]:
    return {
        cast(Table, mapper.local_table).name: mapper.class_
        for mapper in Base.registry.mappers
        if issubclass(mapper.class_, TenantScopedMixin)
    }


# ---------------------------------------------------------------- scope rules ----


def test_no_scope_by_default() -> None:
    assert current_tenant_id() is None
    assert system_scope_reason() is None


def test_tenant_scope_sets_and_restores() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    with tenant_scope(a):
        assert current_tenant_id() == a
        with tenant_scope(b):
            assert current_tenant_id() == b
        assert current_tenant_id() == a
    assert current_tenant_id() is None


def test_tenant_scope_inside_system_scope_drops_system_rights() -> None:
    tenant = uuid.uuid4()
    with system_scope("test.nesting"):
        with tenant_scope(tenant):
            assert system_scope_reason() is None
            assert current_tenant_id() == tenant
        assert system_scope_reason() == "test.nesting"
    assert system_scope_reason() is None


def test_scope_restored_after_exception() -> None:
    with pytest.raises(RuntimeError), tenant_scope(uuid.uuid4()):
        raise RuntimeError("boom")
    assert current_tenant_id() is None


def test_tenant_id_must_be_a_uuid() -> None:
    with pytest.raises(TypeError), tenant_scope("not-a-uuid"):  # type: ignore[arg-type]
        pass


def test_system_scope_needs_a_reason() -> None:
    with pytest.raises(ValueError, match="reason"), system_scope("  "):
        pass


def test_concurrent_tasks_do_not_share_scope() -> None:
    async def run_as(tenant: uuid.UUID) -> uuid.UUID | None:
        with tenant_scope(tenant):
            await asyncio.sleep(0.01)  # let the other task run in between
            return current_tenant_id()

    async def main() -> list[uuid.UUID | None]:
        return list(await asyncio.gather(run_as(a), run_as(b)))

    a, b = uuid.uuid4(), uuid.uuid4()
    assert asyncio.run(main()) == [a, b]


# --------------------------------------------------------------- schema guards ----


def test_every_table_with_tenant_id_uses_the_mixin() -> None:
    scoped = set(tenant_scoped_tables())
    with_column = {t.name for t in Base.metadata.sorted_tables if "tenant_id" in t.c}
    assert with_column == scoped, "a table has tenant_id but is not TenantScopedMixin (or v.v.)"


@pytest.mark.parametrize("table_name", sorted(tenant_scoped_tables()))
def test_tenant_scoped_tables_are_composite_fk_targets(table_name: str) -> None:
    table = Base.metadata.tables[table_name]
    assert not table.c.tenant_id.nullable
    assert any(
        isinstance(c, UniqueConstraint) and [col.name for col in c.columns] == ["tenant_id", "id"]
        for c in table.constraints
    )


@pytest.mark.parametrize("table_name", sorted(tenant_scoped_tables()))
def test_references_between_tenant_tables_include_tenant_id(table_name: str) -> None:
    """A tenant-scoped child must point at a tenant-scoped parent via (tenant_id, id)."""
    scoped = set(tenant_scoped_tables())
    table = Base.metadata.tables[table_name]
    for fk in table.constraints:
        if not isinstance(fk, ForeignKeyConstraint) or fk.referred_table.name not in scoped:
            continue
        local = [c.name for c in fk.columns]
        remote = [e.column.name for e in fk.elements]
        message = f"{table_name} -> {fk.referred_table.name} must use tenant_foreign_key()"
        assert local[0] == "tenant_id", message
        assert remote[0] == "tenant_id", message
