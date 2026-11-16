# Office-Mates

Enterprise AI knowledge and workflow assistant: grounded, permission-aware answers with citations over an organisation's own documents.

> **Status: Phase 0 (foundations) in progress.** Only what is listed under *Implemented* below works today. See [docs/BLUEPRINT.md](docs/BLUEPRINT.md) for the design and [docs/CHECKLIST.md](docs/CHECKLIST.md) for progress.

## Implemented
- Backend skeleton (FastAPI): app factory, typed settings, structured JSON logging, RFC 9457 error responses, request IDs, security headers, `/healthz`, `/readyz`, `/version`.
- Frontend shell (Next.js 16, TypeScript, Tailwind, shadcn/ui): sidebar layout, light/dark theme, typed API client generated from the backend's OpenAPI schema, live system-status card. Sidebar features are shown disabled with the phase they arrive in.

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

## Local development (backend)
Requirements: Python 3.13, [uv](https://docs.astral.sh/uv/).

```bash
cd apps/backend
uv sync
uv run uvicorn officemates.main:app --reload
uv run pytest
```

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
