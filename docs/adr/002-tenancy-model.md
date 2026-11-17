# ADR 002 — Shared-schema tenancy enforced by a fail-closed ORM layer

- **Status:** Accepted — to be implemented in Phase 1 (not built yet)
- **Date:** 2026-11-17
- **Blueprint:** D0, D1, §4.2, §8.1, R3

## Context
Every organisation (tenant) must only ever see its own users, documents, chunks, conversations and
audit logs. The system of record is **MySQL 8.4** (D0). Unlike PostgreSQL, MySQL has **no
Row-Level Security**, so the database itself cannot enforce "this session only sees tenant X's
rows". Isolation therefore has to live in the application, and it has to fail safe: forgetting a
filter must produce an error, not someone else's data. We expect a handful of tenants in the
private deployment, but the design must hold if that grows (blueprint §1.6).

## Decision
**One database, one shared schema, a `tenant_id` column on every tenant-scoped row**, enforced in
layers:

1. **`TenantScopedMixin`** on every tenant-scoped SQLAlchemy model adds
   `tenant_id BINARY(16) NOT NULL`.
2. **Request-scoped `TenantContext`** is set by the API from the authenticated session (never from
   request input).
3. **Fail-closed ORM hooks:**
   - a `do_orm_execute` hook adds `with_loader_criteria(tenant_id == ctx.tenant_id)` to every
     SELECT, UPDATE and DELETE on tenant-scoped models;
   - a `before_insert` hook stamps `tenant_id` from the context;
   - a query on a tenant-scoped model **with no tenant context raises**. The only bypass is an
     explicit `system_scope()` (for migrations, tenant deletion, platform jobs), which is audited.
4. **Composite foreign keys `(tenant_id, id)`** on child tables, so a row physically cannot
   reference another tenant's parent row. Indexes lead with `tenant_id`.
5. **Raw SQL is banned outside the repository layer** (lint rule + review).
6. Least-privilege MySQL accounts (already in place): `app_rw` has DML only, `migrator` has DDL and
   is used only by migrations, `readonly_ops` reads. `audit_logs` is append-only for `app_rw`.

## Alternatives considered
- **Database (or schema) per tenant** — strongest isolation, but N migrations per deploy, N
  connection pools and much more operational work on a single small host. Out of proportion for our
  scale.
- **MySQL views with definer rights / session variables** — emulates RLS, but is fragile, easy to
  bypass from the ORM, and hard to test.
- **Manual `WHERE tenant_id = …` in each query** — one forgotten filter is a leak. Rejected in
  favour of automatic, fail-closed scoping.
- **PostgreSQL with RLS** — the original brief; replaced by MySQL in blueprint v0.2 by the owner's
  choice. This ADR is the cost of that choice.

## Consequences
- ✅ Simple operations: one schema, one migration run, one connection pool.
- ✅ Forgetting a filter fails loudly rather than leaking; cross-tenant references are rejected by
  the database itself.
- ❌ Weaker than database-enforced RLS: a raw-SQL bug or misuse of `system_scope()` could bypass the
  ORM layer. Mitigated by the raw-SQL ban, auditing of `system_scope()` and the tests below — not
  eliminated.
- ❌ Every child table carries `tenant_id` and composite keys, which makes the schema and
  migrations a little more verbose.
- ❌ Noisy-neighbour risk: one tenant's heavy load affects others. Acceptable for our use; per-tenant
  rate limits and budgets come in Phase 3.

## How we check it
Phase 1 exit criterion: two tenants cannot read, update or delete each other's rows through any
repository or ORM path, and un-scoped queries fail closed. Concretely, CI runs:
- a test that **fails if any table with a `tenant_id` column lacks the mixin**;
- **generated per-model cross-tenant tests** (tenant A cannot select, update or delete tenant B's
  rows; a query without tenant context raises);
- composite-FK tests (inserting a child that points at another tenant's parent fails);
- the authz matrix (role × endpoint).
