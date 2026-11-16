# Office-Mates

Enterprise AI knowledge and workflow assistant: grounded, permission-aware answers with citations over an organisation's own documents.

> **Status: Phase 0 (foundations) in progress.** Only what is listed under *Implemented* below works today. See [docs/BLUEPRINT.md](docs/BLUEPRINT.md) for the design and [docs/CHECKLIST.md](docs/CHECKLIST.md) for progress.

## Implemented
- Backend skeleton (FastAPI): app factory, typed settings, structured JSON logging, RFC 9457 error responses, request IDs, `/healthz`, `/readyz`, `/version`.

## Not yet implemented
Everything else in the blueprint: auth, Knowledge Hub, ingestion, assistant, RAG, agents, tools, security center, evaluation, observability, deployment.

## Repository layout
```
apps/backend   Python API + workers (FastAPI, Celery)   — uv-managed
apps/web       Next.js frontend                          — (Phase 0, next)
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

## Licence
Private. All rights reserved.
