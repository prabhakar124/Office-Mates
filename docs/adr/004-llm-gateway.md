# ADR 004 — Provider-agnostic LLM gateway, Anthropic Claude as primary

- **Status:** Accepted — to be implemented in Phase 3 (not built yet)
- **Date:** 2026-11-17
- **Blueprint:** D6, D7, Q1, §7.1, §11.7, R2

## Context
Many parts of the system call an LLM: answer synthesis, supervisor routing, evidence grading,
query rewriting, security classifiers and offline evaluation. Each call needs the same things —
timeouts, retries, streaming, structured output, token counting, cost accounting, per-tenant
budgets, a global spend cap and a kill switch. The budget is "as low as possible" (Q3), so cost
control must be central, not sprinkled across call sites. Model and provider choices should be
changeable by configuration and justified by evals.

## Decision
- A thin internal **`LLMGateway` interface** in `officemates/llm/` is the *only* way application
  code talks to a model. It offers: chat, streaming, structured output (validated by Pydantic),
  token counting, and cost per call.
- The gateway owns **cross-cutting controls**: timeouts, retries with backoff, per-user/tenant/day
  token budgets, global daily spend cap, kill switch, usage records and tracing (Langfuse/OTel).
- **Primary provider: Anthropic Claude** (Q1), with two tiers resolved from config:
  - *fast* — `claude-haiku-5-5`: routing, grading, guards, and answers by default under the
    minimum-cost profile;
  - *strong* — `claude-sonnet-5-5`: enabled per route only when evals show it is worth the cost.
  Model IDs live in configuration, never in code.
- Prompt caching for stable system prompts; output-token caps; small contexts (top ~6 chunks).
- **LangGraph orchestrates; the gateway executes.** Graph nodes call the gateway rather than
  provider-specific model classes. The chat graph runs in the API process for low-latency streaming
  (D7); long jobs (reports, evals) go to Celery.
- Embeddings and reranking use a sibling gateway (local `fastembed`/cross-encoder by default, D4/D5)
  with the same pluggable shape.
- In CI the gateway is **mocked**; only the budget-capped eval-smoke job makes real calls.

## Alternatives considered
- **LangChain model classes everywhere** — fastest start, but retries, budgets and cost accounting
  end up duplicated or bolted on per call site, and library churn (R9) leaks into every module.
- **Call the provider SDK directly from each module** — no abstraction cost, but no single place to
  enforce spend limits or swap providers.
- **A hosted LLM proxy/router service** — another dependency and bill; the gateway is small enough to
  own.

## Consequences
- ✅ One place enforces budgets, the kill switch and cost recording — the main defence against
  runaway spend (R2).
- ✅ Switching models or adding a fallback provider (Phase 10) is a config/adapter change.
- ✅ Eval runs can compare model tiers by config alone.
- ❌ We maintain an adapter and must keep it current with provider features (streaming events, tool
  use, caching). Kept thin to limit this.
- ❌ Provider-specific features beyond the interface need deliberate additions rather than being
  available everywhere.
- ❌ In-process graphs tie up an API worker during slow LLM calls → async I/O everywhere, strict
  timeouts and step/token budgets.

## How we check it
- A lint/review rule: no direct provider SDK imports outside `officemates/llm/`.
- Unit tests for budget enforcement, kill switch, retry/timeout behaviour and cost calculation
  against the cost table.
- `usage_records` and Langfuse traces show tokens and cost for every request (Phase 3 exit).
