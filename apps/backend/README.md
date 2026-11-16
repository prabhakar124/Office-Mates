# Office-Mates backend

FastAPI API (and, from Phase 2, Celery workers) sharing one Python package: `officemates`.

```bash
uv sync                                          # install deps into .venv
uv run uvicorn officemates.main:app --reload     # http://localhost:8000/healthz
uv run pytest                                    # tests
uv run ruff check . && uv run ruff format --check .
uv run mypy
```

Configuration comes from environment variables prefixed `OM_` (see `.env.example`).
