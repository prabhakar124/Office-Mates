# ADR 001 — Monorepo with one backend codebase and image

- **Status:** Accepted — implemented in Phase 0
- **Date:** 2026-11-17
- **Blueprint:** §2.2, §2.5, D14

## Context
Office-Mates has a Python backend (REST API, SSE chat, Celery workers), a Next.js frontend, local
infrastructure (Docker Compose), future cloud infrastructure (Terraform), versioned evaluation
datasets and design docs. One developer builds it. The frontend's API types must stay in step with
the backend's contract, and domain logic (chunking, retrieval, permissions) must never exist in two
copies that can drift — a drifted permission check is a security bug.

## Decision
One git repository, laid out as:

```
apps/backend   Python package `officemates` (uv-managed): API, workers, migrations, scripts
apps/web       Next.js + TypeScript (npm-managed)
infra/         docker/ (Compose helpers, deployment compose files) and terraform/ (Phase 4)
evals/         versioned golden datasets and red-team suites
docs/          blueprint, checklist, ADRs, runbooks
compose.yaml   local stack, at the repo root
```

- The API and the Celery worker are **one Python codebase built into one image**
  (`officemates-backend`) with different entrypoints. Migrations run from the same image as a
  one-shot Compose job.
- Each app keeps its own `Dockerfile` and toolchain lockfile (`uv.lock`, `package-lock.json`).
  There is no cross-language build tool (no Nx/Turborepo/Bazel).
- The frontend's API client is generated from the backend's OpenAPI schema
  (`apps/web/lib/api/openapi.json` → `schema.d.ts`). CI fails if the committed schema does not
  match what the backend produces.
- One set of repo-wide checks: pre-commit (gitleaks, Ruff, mypy, ESLint, Prettier, tsc) and one CI
  workflow covering both apps.

## Alternatives considered
- **Separate repositories for backend and frontend** — clean ownership boundaries, but contract
  changes need coordinated PRs across repos, and versioning the generated client becomes its own
  chore. Not worth it for one developer.
- **Separate images for API and worker** — slightly smaller images, but invites copying domain code
  or splitting it into a shared library we would have to version. One image keeps one source of
  truth.
- **A monorepo build tool** — adds a learning curve and config for only two apps with independent
  native toolchains.

## Consequences
- ✅ A backend contract change, its regenerated client and the UI that uses it land in one commit
  and are checked together in CI.
- ✅ Permission, tenancy and retrieval code exists once and is shared by API, agents and workers.
- ✅ Local stack starts with one `docker compose up`.
- ❌ The worker image carries API dependencies it does not use (and later the API image carries
  parsing/embedding libraries). Acceptable; revisit if image size or cold starts hurt.
- ❌ CI runs both apps' jobs even for a one-sided change, until we add path filters.
- ❌ The repo is public (blueprint §11.8), so everything here is readable by anyone — secrets, real
  data and infrastructure identifiers must stay out of it (enforced by gitleaks and the `.env`
  blocker).

## How we check it
- CI: API-contract check (generated schema matches committed schema), backend and web jobs, Docker
  stack smoke test.
- Code review: no domain logic in `apps/web` beyond presentation; no second copy of backend logic in
  any service.
