"""Tenant isolation against the real MySQL (ADR 002, Phase 1 exit criterion).

Two tenants must never read, update or delete each other's rows through any ORM path,
and tenant-scoped queries without a tenant must fail instead of returning everything.

Every tenant-scoped model needs a factory in ``ROW_FACTORIES``; a test fails when a new
model is added without one, so the cross-tenant checks below cover it automatically.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from typing import Any

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from officemates.audit.models import AuditLog
from officemates.core.tenancy import system_scope, tenant_scope
from officemates.db.models import Base
from officemates.db.session import create_engine, create_session_factory
from officemates.db.tenancy import (
    CrossTenantWriteError,
    TenantContextMissingError,
    TenantScopedMixin,
    UnscopedTableAccessError,
)
from officemates.identity.models import Membership, Role, Tenant, User
from tests.integration.conftest import DbUrls
from tests.test_tenancy_unit import tenant_scoped_tables

pytestmark = pytest.mark.integration

MEMBERSHIPS = Base.metadata.tables["memberships"]  # the plain Core table


@dataclass
class World:
    tenant_a: uuid.UUID
    tenant_b: uuid.UUID
    user_a: uuid.UUID
    user_b: uuid.UUID


RowFactory = Callable[[World, uuid.UUID], TenantScopedMixin]

ROW_FACTORIES: dict[type[TenantScopedMixin], RowFactory] = {
    Membership: lambda w, t: Membership(
        tenant_id=t,
        user_id=_new_user_id(w, t),
        role=Role.MEMBER,
    ),
    AuditLog: lambda w, t: AuditLog(
        tenant_id=t,
        actor_user_id=w.user_a if t == w.tenant_a else w.user_b,
        action="test.event",
    ),
}

_extra_users: dict[uuid.UUID, list[User]] = {}


def _new_user_id(world: World, tenant: uuid.UUID) -> uuid.UUID:
    # Memberships are unique per (tenant, user), so each new row needs its own user.
    user = User(id=uuid.uuid4(), email=f"{uuid.uuid4().hex}@example.test", display_name="X")
    _extra_users.setdefault(tenant, []).append(user)
    return user.id


def run[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


async def with_session[T](
    urls: DbUrls, work: Callable[[AsyncSession], Awaitable[T]], *, commit: bool = True
) -> T:
    engine = create_engine(urls.app, pool_size=1, max_overflow=0)
    factory: async_sessionmaker[AsyncSession] = create_session_factory(engine)
    try:
        async with factory() as session:
            result = await work(session)
            if commit:
                await session.commit()
            return result
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def world(migrated_db: DbUrls) -> World:
    async def seed(session: AsyncSession) -> World:
        w = World(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
        session.add_all(
            [
                Tenant(id=w.tenant_a, name="Acme", slug=f"acme-{w.tenant_a.hex[:8]}"),
                Tenant(id=w.tenant_b, name="Globex", slug=f"globex-{w.tenant_b.hex[:8]}"),
                User(id=w.user_a, email=f"a-{w.user_a.hex}@example.test", display_name="A"),
                User(id=w.user_b, email=f"b-{w.user_b.hex}@example.test", display_name="B"),
            ]
        )
        await session.flush()
        session.add_all(
            [
                Membership(tenant_id=w.tenant_a, user_id=w.user_a, role=Role.OWNER),
                Membership(tenant_id=w.tenant_b, user_id=w.user_b, role=Role.OWNER),
            ]
        )
        return w

    with system_scope("test.seed"):
        return run(with_session(migrated_db, seed))


def _create_rows(urls: DbUrls, world: World, model: type[TenantScopedMixin]) -> dict[str, Any]:
    """One fresh row of ``model`` in each tenant; returns their ids by tenant letter."""

    async def work(session: AsyncSession) -> dict[str, Any]:
        rows = {"a": ROW_FACTORIES[model](world, world.tenant_a)}
        rows["b"] = ROW_FACTORIES[model](world, world.tenant_b)
        for users in _extra_users.values():
            session.add_all(users)
        _extra_users.clear()
        await session.flush()
        session.add_all(rows.values())
        await session.flush()
        return {k: v.id for k, v in rows.items()}  # type: ignore[attr-defined]

    with system_scope("test.seed"):
        return run(with_session(urls, work))


# ------------------------------------------------------------ coverage guard ----


def test_every_tenant_scoped_model_has_a_factory() -> None:
    assert set(ROW_FACTORIES) == set(tenant_scoped_tables().values())


# ----------------------------------------------- generated per-model isolation ----


@pytest.mark.parametrize("model", list(ROW_FACTORIES), ids=lambda m: m.__tablename__)
def test_tenant_cannot_read_other_tenants_rows(
    migrated_db: DbUrls, world: World, model: Any
) -> None:
    ids = _create_rows(migrated_db, world, model)

    async def work(session: AsyncSession) -> tuple[set[uuid.UUID], set[uuid.UUID], Any, Any]:
        tenants = set((await session.scalars(select(model.tenant_id))).all())
        found = set(
            (await session.scalars(select(model.id).where(model.id.in_(ids.values())))).all()
        )
        by_get = await session.get(model, ids["b"])
        alias = aliased(model)
        via_alias = (await session.scalars(select(alias.id).where(alias.id == ids["b"]))).all()
        return tenants, found, by_get, via_alias

    with tenant_scope(world.tenant_a):
        tenants, found, by_get, via_alias = run(with_session(migrated_db, work))
    assert tenants == {world.tenant_a}
    assert found == {ids["a"]}
    assert by_get is None
    assert via_alias == []


@pytest.mark.parametrize("model", list(ROW_FACTORIES), ids=lambda m: m.__tablename__)
def test_tenant_cannot_update_or_delete_other_tenants_rows(
    migrated_db: DbUrls, world: World, model: Any
) -> None:
    ids = _create_rows(migrated_db, world, model)

    async def work(session: AsyncSession) -> tuple[int, int]:
        updated = await session.execute(
            update(model).where(model.id == ids["b"]).values(created_at=func.now(6))
        )
        deleted = await session.execute(delete(model).where(model.id == ids["b"]))
        return updated.rowcount, deleted.rowcount  # type: ignore[attr-defined]

    with tenant_scope(world.tenant_a):
        assert run(with_session(migrated_db, work)) == (0, 0)

    async def still_there(session: AsyncSession) -> uuid.UUID | None:
        return await session.scalar(select(model.tenant_id).where(model.id == ids["b"]))

    with system_scope("test.verify"):
        assert run(with_session(migrated_db, still_there, commit=False)) == world.tenant_b


# ------------------------------------------------------------ specific paths ----


def test_join_only_sees_own_tenant(migrated_db: DbUrls, world: World) -> None:
    async def work(session: AsyncSession) -> list[uuid.UUID]:
        rows = await session.execute(
            select(User.id).join(Membership, Membership.user_id == User.id)
        )
        return [r[0] for r in rows]

    with tenant_scope(world.tenant_b):
        user_ids = run(with_session(migrated_db, work, commit=False))
    assert world.user_b in user_ids
    assert world.user_a not in user_ids


def _leak_probes(w: World) -> dict[str, Any]:
    """Statement shapes that each select tenant A's membership, run as tenant B."""
    a_rows = Membership.user_id == w.user_a
    return {
        "subquery": select(User.id).where(
            User.id.in_(select(Membership.user_id).where(a_rows).scalar_subquery())
        ),
        "exists": select(User.id).where(
            select(Membership.id).where(Membership.user_id == User.id, a_rows).exists()
        ),
        "union": select(Membership.id)
        .where(a_rows)
        .union(select(Membership.id).where(Membership.user_id == w.user_b)),
        "outer-join": select(Membership.id)
        .select_from(User)
        .outerjoin(Membership, Membership.user_id == User.id)
        .where(a_rows),
        "cte": select(select(Membership.id).where(a_rows).cte("leak").c.id),
    }


@pytest.mark.parametrize("shape", ["subquery", "exists", "union", "outer-join", "cte"])
def test_other_query_shapes_are_scoped(migrated_db: DbUrls, world: World, shape: str) -> None:
    async def work(session: AsyncSession) -> list[Any]:
        rows = (await session.execute(_leak_probes(world)[shape])).all()
        return [r[0] for r in rows if r[0] is not None]

    with tenant_scope(world.tenant_b):
        found = run(with_session(migrated_db, work, commit=False))
    if shape == "union":
        assert len(found) == 1  # only tenant B's own row from the second half
    else:
        assert found == [], f"{shape} leaked tenant A rows: {found}"


@pytest.mark.parametrize(
    "statement",
    [
        pytest.param(lambda: select(MEMBERSHIPS.c.id), id="core-select"),
        pytest.param(
            lambda: select(User.id).join(MEMBERSHIPS, MEMBERSHIPS.c.user_id == User.id),
            id="orm-select-joining-core-table",
        ),
        pytest.param(lambda: update(MEMBERSHIPS).values(role=Role.VIEWER), id="core-update"),
        pytest.param(lambda: delete(MEMBERSHIPS), id="core-delete"),
    ],
)
def test_bare_core_table_access_is_refused(
    migrated_db: DbUrls, world: World, statement: Callable[[], Any]
) -> None:
    """The tenant filter attaches to ORM entities only, so Core tables are refused."""

    async def work(session: AsyncSession) -> object:
        return await session.execute(statement())

    with tenant_scope(world.tenant_b), pytest.raises(UnscopedTableAccessError):
        run(with_session(migrated_db, work, commit=False))


def test_aggregates_are_scoped(migrated_db: DbUrls, world: World) -> None:
    async def count(session: AsyncSession) -> int | None:
        return await session.scalar(
            select(func.count()).select_from(Membership).where(Membership.user_id == world.user_a)
        )

    with tenant_scope(world.tenant_b):
        assert run(with_session(migrated_db, count, commit=False)) == 0
    with tenant_scope(world.tenant_a):
        assert run(with_session(migrated_db, count, commit=False)) == 1


def test_system_scope_sees_all_tenants(migrated_db: DbUrls, world: World) -> None:
    async def work(session: AsyncSession) -> set[uuid.UUID]:
        return set((await session.scalars(select(Membership.tenant_id))).all())

    with system_scope("test.platform"):
        assert {world.tenant_a, world.tenant_b} <= run(with_session(migrated_db, work))


# ---------------------------------------------------------------- fail closed ----


def test_query_without_scope_raises(migrated_db: DbUrls, world: World) -> None:
    async def work(session: AsyncSession) -> object:
        return (await session.scalars(select(Membership))).all()

    with pytest.raises(TenantContextMissingError):
        run(with_session(migrated_db, work, commit=False))


def test_bulk_update_without_scope_raises(migrated_db: DbUrls, world: World) -> None:
    async def work(session: AsyncSession) -> object:
        return await session.execute(update(Membership).values(role=Role.VIEWER))

    with pytest.raises(TenantContextMissingError):
        run(with_session(migrated_db, work, commit=False))


def test_platform_tables_need_no_scope(migrated_db: DbUrls, world: World) -> None:
    async def work(session: AsyncSession) -> User | None:
        return await session.get(User, world.user_a)

    assert run(with_session(migrated_db, work, commit=False)) is not None


# --------------------------------------------------------------------- writes ----


def test_insert_is_stamped_with_current_tenant(migrated_db: DbUrls, world: World) -> None:
    async def work(session: AsyncSession) -> uuid.UUID:
        row = AuditLog(action="test.stamped")  # no tenant_id given
        session.add(row)
        await session.flush()
        return row.tenant_id

    with tenant_scope(world.tenant_b):
        assert run(with_session(migrated_db, work)) == world.tenant_b


def test_insert_into_other_tenant_raises(migrated_db: DbUrls, world: World) -> None:
    async def work(session: AsyncSession) -> None:
        session.add(AuditLog(tenant_id=world.tenant_b, action="test.smuggled"))
        await session.flush()

    with tenant_scope(world.tenant_a), pytest.raises(CrossTenantWriteError):
        run(with_session(migrated_db, work))


def test_insert_without_scope_raises(migrated_db: DbUrls, world: World) -> None:
    async def work(session: AsyncSession) -> None:
        session.add(AuditLog(tenant_id=world.tenant_a, action="test.unscoped"))
        await session.flush()

    with pytest.raises(TenantContextMissingError):
        run(with_session(migrated_db, work))


def test_moving_a_row_to_another_tenant_raises(migrated_db: DbUrls, world: World) -> None:
    async def work(session: AsyncSession) -> None:
        membership = await session.scalar(
            select(Membership).where(Membership.user_id == world.user_a)
        )
        assert membership is not None
        membership.tenant_id = world.tenant_b
        await session.flush()

    with tenant_scope(world.tenant_a), pytest.raises(CrossTenantWriteError):
        run(with_session(migrated_db, work))


@pytest.mark.parametrize("scope", ["tenant", "system"])
def test_bulk_update_of_tenant_id_raises(migrated_db: DbUrls, world: World, scope: str) -> None:
    async def work(session: AsyncSession) -> object:
        return await session.execute(
            update(Membership)
            .where(Membership.user_id == world.user_a)
            .values(tenant_id=world.tenant_b)
        )

    ctx = tenant_scope(world.tenant_a) if scope == "tenant" else system_scope("test.move")
    with ctx, pytest.raises(CrossTenantWriteError):
        run(with_session(migrated_db, work))


# ------------------------------------------------------------- audit log rules ----


@pytest.mark.parametrize("operation", ["update", "delete"])
def test_audit_log_is_append_only(migrated_db: DbUrls, world: World, operation: str) -> None:
    async def work(session: AsyncSession) -> None:
        row = AuditLog(action="test.immutable")
        session.add(row)
        await session.flush()
        if operation == "update":
            await session.execute(
                update(AuditLog).where(AuditLog.id == row.id).values(action="test.rewritten")
            )
        else:
            await session.execute(delete(AuditLog).where(AuditLog.id == row.id))

    with tenant_scope(world.tenant_a), pytest.raises(DBAPIError, match="append-only"):
        run(with_session(migrated_db, work))


# ---------------------------------------------------------- migrations == models ----


def test_migrations_match_the_models(migrated_db: DbUrls) -> None:
    async def diff() -> list[Any]:
        engine = create_engine(migrated_db.migrator, pool_size=1, max_overflow=0)
        try:
            async with engine.connect() as conn:
                return await conn.run_sync(
                    lambda sync: compare_metadata(
                        MigrationContext.configure(sync, opts={"compare_type": True}),
                        Base.metadata,
                    )
                )
        finally:
            await engine.dispose()

    assert run(diff()) == []
