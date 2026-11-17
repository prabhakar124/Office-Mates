# ADR 003 — One Pinecone index, one namespace per tenant

- **Status:** Accepted — to be implemented in Phase 2. The Pinecone behaviours it relies on are
  verified by contract tests against the real service (2026-11-17).
- **Revised:** 2026-11-17 — testing moved from Pinecone Local to the real service (see *How we
  check it*).
- **Date:** 2026-11-17
- **Blueprint:** D0, D2, §4.3, §6.2, §8.1, §11.4

## Context
Chunk embeddings live in **Pinecone serverless** (D0), a third-party service outside our MySQL
tenancy guarantees ([ADR 002](002-tenancy-model.md)). Retrieval is the most likely place for a
cross-tenant leak: one wrong filter in a vector query returns another organisation's content, and
agents and tools will build queries partly from LLM output. We are on Pinecone's free **Starter**
plan: one project, up to 5 indexes, 100 namespaces per index, us-east-1 only.

## Decision
- **One serverless index per environment and version** (`om-chunks-{env}-v{n}`, dense, cosine).
- **One namespace per tenant**, `t_{tenant_id}`, stored on `tenants.pinecone_namespace`. Eval runs
  use their own `eval_{dataset}_{version}` namespaces and never touch tenant data.
- **Only the retrieval layer chooses the namespace**, from the authenticated tenant, via
  `RetrievalScope.for_principal(user, tenant)` — the single code path to Pinecone. Agents and tools
  may pass *optional* filters, which are AND-ed with the mandatory ones and never replace them; they
  can never name a namespace.
- **Document ACLs are metadata filters inside the namespace** (`visibility`, `acl_principals`).
- **Record ids are `{document_version_id}#{chunk_index}`**, so every vector of a document version
  can be listed and deleted by id prefix.
- **No chunk text in Pinecone.** Metadata is small and filter-only; text stays in MySQL and is
  loaded by `chunk_id` **through the tenant-scoped ORM** after retrieval — so a vector that somehow
  came from the wrong namespace loads nothing.
- MySQL is the source of truth; any index can be rebuilt from `chunks`. Model changes build a new
  index version, are evaluated, then switched in config.
- Deleting a tenant deletes its namespace plus its MySQL rows in one idempotent, audited job.

## Alternatives considered
- **One shared namespace with a `tenant_id` metadata filter** — a single missing or overwritten
  filter leaks across tenants. Namespaces make the boundary physical: a query cannot cross them.
- **Index per tenant** — strongest separation, but the Starter plan allows only 5 indexes, and
  cost and management grow per tenant.
- **Self-hosted vector DB (Qdrant/pgvector)** — the original brief; replaced by Pinecone in v0.2 to
  avoid running and sizing a vector database on the lean host.

## Consequences
- ✅ Cross-tenant vector queries are impossible by construction, not by filter discipline.
- ✅ Tenant deletion is a namespace delete; re-indexing never needs Pinecone backups.
- ✅ Pinecone never receives chunk text, emails or conversation content — only embeddings and filter
  metadata.
- ❌ Cross-tenant or global search is impossible — which we never want.
- ❌ 100 namespaces per index caps tenants + eval namespaces on the free plan. Fine for our own use;
  an upgrade trigger if Phase D (public demo) opens.
- ❌ Starter has one project for everything (dev, CI, staging, prod). We use a separate API key per
  environment inside it so each can be revoked alone; separate projects on upgrade.
- ❌ An extra MySQL round-trip per query to fetch chunk text.
- ❌ Pinecone is eventually consistent; ingestion must verify record counts before marking a
  document `ready` (the contract tests poll for the same reason).
- ❌ No offline development or testing for vector code: it needs network access and an API key.

## How we check it
- **Contract tests against real Pinecone** (`apps/backend/tests/integration/test_pinecone_contract.py`,
  marker `pinecone`): namespace isolation for query and fetch, every filter shape we use (`$eq`,
  `$in`/`$nin` on list fields, integer date ranges, mandatory ACL `$and` user filter), exact and
  paged list-by-prefix, delete by id prefix, namespace deletion leaving other tenants intact, and
  dimension validation. They use a small dedicated index (`om-contract-test`) and throwaway
  `ct_<run>_*` namespaces deleted after each run (stale ones are swept), so they never touch real
  data. They need `PINECONE_API_KEY` (git-ignored `.env` locally, a repository secret in CI) and are
  skipped without it — fork PRs get no secret.
- **Pinecone leakage tests** for `RetrievalScope` (Phase 2) build on the same fixtures: queries for
  tenant A never return tenant B's ids, including when callers pass hostile filters.
- Unit tests that `RetrievalScope` always sets the namespace and mandatory filters, and that
  caller filters cannot remove them.
- Output-side check: citation chunk ids are re-verified against the tenant before streaming.
- Unit tests of retrieval code may use an in-process fake; anything the fake does must also be
  covered by a contract test, so the fake cannot drift from the real service.

### Why not an emulator
Pinecone Local reached end of life on 2026-10-07. Its last image (February 2025) still isolates
namespaces and applies filters, but it cannot create an index with the current SDK (10.x) and has
no namespace API (`delete_namespace` returns 404) — the exact call tenant deletion depends on.
Pinecone's suggested replacement is a stateless API mock that returns canned responses, which
cannot test isolation at all. Real-service tests cost a few dozen read/write units per run out of
the Starter plan's 1M/2M monthly allowance and add network latency (~20–30 s per run), which we
accept.
