# ADR 005 — Lean single-host AWS profile, Terraform-ready for Scaled

- **Status:** Accepted — to be implemented in Phase 4 (not built yet). **Q8 (private access
  method) is still open** and must be decided before the first deployment.
- **Date:** 2026-11-17
- **Blueprint:** D12, §11.1–11.3, §11.7, Q2, Q3, Q10, Q11, R2, R7

## Context
The first deployment is **private and invite-only, for our own use** — a handful of users. The
monthly budget is "as low as possible" (Q3). Pinecone's free Starter plan only offers indexes in
**us-east-1** (§11.4). We want the option of a larger, more resilient setup later without
re-architecting.

## Decision
- **Region:** AWS us-east-1, next to the Pinecone index (no cross-region latency or transfer cost).
- **"Lean" profile (default):** one ARM EC2 instance (start at ~4 GB RAM) running the same Docker
  Compose services as local development — web, api, worker, beat, MySQL 8.4, Redis — with:
  - Caddy for TLS at the edge;
  - S3 for files (private, all public access blocked, encrypted, pre-signed URLs);
  - ECR for images, SSM Parameter Store for secrets, IAM via GitHub Actions OIDC (no long-lived
    keys);
  - nightly `mysqldump --single-transaction` to S3, plus a backup before every migration;
  - Pinecone Starter (rebuildable from MySQL, so no separate vector backup).
- **Minimum-cost levers:** no NAT gateway, ALB, RDS, ElastiCache, CloudFront/WAF or multi-AZ;
  auto-stop the instance outside working hours; AWS Budgets alarms at 50/80/100%; free tiers for
  Langfuse, Grafana Cloud and GitHub Actions (public repo).
- **Terraform** is written so a **"Scaled" profile** (ECS Fargate + ALB, RDS/Aurora MySQL,
  ElastiCache, Secrets Manager, CloudFront/WAF) is a variable flip, using the same images.
- **Private access:** public sign-up disabled everywhere; network restricted by either
  (a) an IP allowlist or (b) no public ports via a private network such as Tailscale.
  Recommended: (b). **Decision pending (Q8).** `/ops`, Langfuse, OpenAPI docs, Terraform state and
  keys stay private regardless.
- Deploys: build → scan → push to ECR → backup → Alembic migrations → restart → `/readyz` smoke
  test → automatic rollback to the previous tag on failure.

## Alternatives considered
- **Scaled profile from day one** — RDS, ElastiCache, ALB and NAT alone cost far more per month than
  a single instance, for users we do not have.
- **Managed PaaS (Render, Fly.io, Railway)** — simpler, but less control over network privacy,
  harder to keep next to Pinecone in us-east-1, and pricing that grows with each service.
- **Run at home / on a laptop** — free, but not reachable reliably and no backups or TLS story.

## Consequences
- ✅ Very low running cost, and production runs the same Compose stack we test locally.
- ✅ Growing up is a Terraform variable, not a rewrite.
- ❌ **Single point of failure** with no autoscaling: an instance failure means downtime until it is
  restored from backups. Acceptable for private, own use.
- ❌ MySQL on the instance means we own its backups and restore — so restore must be tested once
  before the MVP is called done.
- ❌ Embeddings, the reranker, MySQL and the app share one box (R7) — benchmark in Phases 2 and 5,
  and move to a bigger instance or hosted reranker if needed.
- ❌ Auto-stop means the app is unavailable outside configured hours.

## How we check it
Phase 4 exit: the deployment works for invited users only; backup restore and the
Pinecone-rebuild-from-MySQL script have each been tested once; budget alarm, spend alert and uptime
check are in place; the network restriction chosen in Q8 is verified from outside.
