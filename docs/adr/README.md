# Architecture Decision Records

Short records of decisions that are expensive to reverse. Each one says what we chose, what we
turned down, and what it costs us. The full design lives in [BLUEPRINT.md](../BLUEPRINT.md); an ADR
is written when a blueprint decision (§3) is adopted, and updated or superseded rather than
silently edited when it changes.

| # | Title | Status | Blueprint |
|---|-------|--------|-----------|
| [001](001-monorepo.md) | Monorepo with one backend codebase and image | Accepted — implemented (Phase 0) | §2.2, §2.5, D14 |
| [002](002-tenancy-model.md) | Shared-schema tenancy enforced by a fail-closed ORM layer | Accepted — to be implemented in Phase 1 | D0, D1, §4.2 |
| [003](003-vector-isolation.md) | One Pinecone index, one namespace per tenant | Accepted — to be implemented in Phase 2 | D2, §4.3, §6.2 |
| [004](004-llm-gateway.md) | Provider-agnostic LLM gateway, Anthropic Claude as primary | Accepted — to be implemented in Phase 3 | D6, D7, Q1 |
| [005](005-hosting-profile.md) | Lean single-host AWS profile, Terraform-ready for Scaled | Accepted — to be implemented in Phase 4 (Q8 open) | D12, §11, Q2, Q3 |

## Format
Each ADR has: **Status**, **Context**, **Decision**, **Alternatives considered**, **Consequences**
(good and bad), and **How we check it** — the tests or reviews that keep the decision true.

New ADRs take the next number. To change a decision, write a new ADR that supersedes the old one
and set the old one's status to *Superseded by NNN*.
