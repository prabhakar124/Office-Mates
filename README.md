# Office-Mates

Enterprise AI knowledge and workflow assistant: grounded, permission-aware answers with citations over an organisation's own documents.

> **Status: Phase 0 (foundations) in progress.** Only what is listed under *Implemented* below works today. See [docs/BLUEPRINT.md](docs/BLUEPRINT.md) for the design and [docs/CHECKLIST.md](docs/CHECKLIST.md) for progress.

## Implemented
- Backend skeleton (FastAPI): app factory, typed settings, structured JSON logging, RFC 9457 error responses, request IDs, security headers, `/healthz`, `/readyz`, `/version`.
- Frontend shell (Next.js 16, TypeScript, Tailwind, shadcn/ui): sidebar layout, light/dark theme, typed API client generated from the backend's OpenAPI schema, live system-status card. Sidebar features are shown disabled with the phase they arrive in.

- Local stack with Docker Compose: MySQL 8.4, Redis, Pinecone Local, SeaweedFS (S3 stand-in), API, Celery worker and web app. The worker has one connectivity task; MySQL, Pinecone and S3 are running but not used by the app yet.
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
| Pinecone Local | http://localhost:5080 |

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

## Licence
Copyright © 2026. All rights reserved. The source is public to read; no licence is granted to use, copy or redistribute it.

## Security
Never commit secrets. Configuration lives in git-ignored `.env` files; see the `.env.example` files for the variables.
