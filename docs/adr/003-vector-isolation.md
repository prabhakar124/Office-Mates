# ADR 003 — One Pinecone index, one namespace per tenant

- **Status:** Accepted — to be implemented in Phase 2 (not built yet). Pinecone Local parity check
  still open (Phase 0 checklist).
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
- ❌ Starter has one project, so staging and prod share an API key (accepted; separate on upgrade).
- ❌ An extra MySQL round-trip per query to fetch chunk text.
- ❌ Pinecone is eventually consistent; ingestion must verify record counts before marking a
  document `ready`.

## How we check it
- **Pinecone leakage tests** in CI against Pinecone Local: queries for tenant A never return
  tenant B's ids, including when callers pass hostile filters.
- Unit tests that `RetrievalScope` always sets the namespace and mandatory filters, and that
  caller filters cannot remove them.
- Output-side check: citation chunk ids are re-verified against the tenant before streaming.
- **Open prerequisite:** confirm Pinecone Local supports namespaces, metadata filters,
  list-by-prefix and delete the way the real service does, and re-check Starter limits (§11.4)
  before Phase 2.
