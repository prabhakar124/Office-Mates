# Office-Mates

Enterprise AI knowledge and workflow assistant: grounded, permission-aware answers with citations over an organisation's own documents.

> **Status: Phase 0 (foundations) complete; Phase 1 (auth, tenants, roles) next.** Only what is listed under *Implemented* below works today. See [docs/BLUEPRINT.md](docs/BLUEPRINT.md) for the design, [docs/adr/](docs/adr/README.md) for the key decisions and [docs/CHECKLIST.md](docs/CHECKLIST.md) for progress.

## Implemented
- Backend skeleton (FastAPI): app factory, typed settings, structured JSON logging, RFC 9457 error responses, request IDs, security headers, `/healthz`, `/readyz`, `/version`.
- Frontend shell (Next.js 16, TypeScript, Tailwind, shadcn/ui): sidebar layout, light/dark theme, typed API client generated from the backend's OpenAPI schema, live system-status card. Sidebar features are shown disabled with the phase they arrive in.

- Local stack with Docker Compose: MySQL 8.4, Redis, SeaweedFS (S3 stand-in), API, Celery worker and web app. The worker has one connectivity task; S3 is running but not used by the app yet.
- Pinecone contract tests: the vector-store behaviours the design relies on (namespace isolation, metadata filters, list/delete by id prefix, namespace deletion) are checked against the real Pinecone service. The app itself does not use Pinecone yet.
- Database foundation: async SQLAlchemy on MySQL, Alembic migrations (run automatically by Docker Compose as a separate `migrator` account), restricted `app_rw` account for the app, time-ordered UUID keys and UTC timestamps. No application tables yet.

## Not yet implemented
Everything else in the blueprint: auth, Knowledge Hub, ingestion, assistant, RAG, agents, tools, security center, evaluation, observability, deployment.

## Repository layout
```
apps/backend   Python API + workers (FastAPI, Celery)   — uv-managed
apps/web       Next.js frontend                          — npm-managed
infra/         Docker and Terraform
evals/         Versioned evaluation datasets
docs/          Blueprint, checklist, ADRs
```

## Run everything with Docker
Requirements: Docker Desktop running.

```bash
cp .env.example .env        # then replace each CHANGE_ME with a password of your own
docker compose up --build -d --wait
```

| Service | URL on your machine |
|---------|---------------------|
| Web app | http://localhost:3000 |
| API | http://localhost:8000/readyz (docs at /docs) |
| MySQL | localhost:3310 (database `officemates`) |
| Redis | localhost:6379 |
| S3 (SeaweedFS) | http://localhost:8333 |

Pinecone is not part of the local stack: there is no supported emulator, so it is used as the real service with `PINECONE_API_KEY` from `.env`.

All ports are bound to 127.0.0.1 only. Stop with `docker compose down` (add `-v` to also delete the data).

## Local development (backend)
Requirements: Python 3.13, [uv](https://docs.astral.sh/uv/).

```bash
cd apps/backend
uv sync
uv run uvicorn officemates.main:app --reload
uv run pytest
```

### Database migrations
Docker Compose applies migrations on start. To work with them by hand, set `OM_DATABASE_MIGRATION_URL` (see `apps/backend/.env.example`) and run from `apps/backend`:

```bash
uv run python -m officemates.db.migrate upgrade head
uv run python -m officemates.db.migrate revision --autogenerate -m "describe the change"
```

Tests marked `integration` use the `officemates_test` database in the Compose MySQL and are skipped if it is not running.

Tests marked `pinecone` run against the real Pinecone service, using `PINECONE_API_KEY` from the root `.env` (or the environment). They use a small dedicated index, `om-contract-test`, created on first run, and throwaway namespaces that are deleted afterwards. Without a key they are skipped. In CI they run when the repository has a `PINECONE_API_KEY` secret.

## Local development (frontend)
Requirements: Node 22+. Start the backend first, then:

```bash
cd apps/web
npm install
npm run dev          # http://localhost:3000
npm run lint && npm run typecheck && npm test
```

After changing backend endpoints, regenerate the typed client:

```bash
cd apps/backend && uv run python -m officemates.scripts.export_openapi ../web/lib/api/openapi.json
cd ../web && npm run gen:api
```

## Pre-commit checks
Run once after cloning, so every commit is checked automatically (secret scan, lint, types, formatting):

```bash
cd apps/backend
uv sync
uv run pre-commit install
```

Run all checks by hand with `uv run pre-commit run --all-files` from `apps/backend`. The first run downloads and builds the secret scanner, which takes a few minutes.

## Continuous integration
`.github/workflows/ci.yml` runs on every push to `main` and on pull requests: a secret scan of the full history, backend lint/type checks/tests against a real MySQL, frontend lint/type checks/tests/build, a check that the generated API client matches the backend, and a build-and-start smoke test of the whole Docker stack. It uses no repository secrets.

## Licence
Copyright © 2026. All rights reserved. The source is public to read; no licence is granted to use, copy or redistribute it.

## Security
Never commit secrets. Configuration lives in git-ignored `.env` files; see the `.env.example` files for the variables.
