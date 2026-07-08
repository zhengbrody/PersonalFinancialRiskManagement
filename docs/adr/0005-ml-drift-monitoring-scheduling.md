# ADR 0005 — ML drift monitoring: GitHub Actions cron + on-demand computation

Date: 2026-07-08 · Status: accepted

## Context

Phase 4 of the ML-lifecycle plan requires scheduled drift checks (PSI/KS of
live features vs the training reference) with alerting. Two candidate
schedulers: an in-process APScheduler job inside the FastAPI backend, or the
repo's existing GitHub Actions cron pattern.

## Decision

**GitHub Actions daily cron curling a public read-only `GET /api/v1/ml/health`
endpoint that computes drift on demand (10-minute in-process cache).**
Alerting lives server-side (structured log + Sentry `capture_message` on the
healthy→watch/drift transition, throttled by the cache), so the verdict is
identical whether a cron, a human, or an uptime probe asks.

## Rationale

- **The box is the constraint.** Production is a single-worker uvicorn on a
  916 MB t3.micro. APScheduler adds a resident thread, memory, and a new
  failure mode (silent scheduler death — invisible until someone checks);
  the box has a history of OOM incidents.
- **Repo convention.** Five GH crons already run (train-regime, db-backup,
  e2e-real, weekly-digest, db-restore-drill): free execution history, red-run
  visibility, manual dispatch, and secrets handling are already understood.
- **On-demand beats push-computed state.** The health endpoint recomputes
  from the same cached serving frame the regime endpoint uses, so there is no
  state file to go stale and no writer to crash; the cron is merely a heartbeat
  that also fails red on `overall_status == "drift"`.
- **Single-worker note.** The 10-minute cache and the transition-edge alert
  throttle are in-process; if uvicorn ever gains workers, both become
  per-worker (same caveat already documented for the /admin metrics counters).

## Consequences

- No new runtime dependency or resident process; the endpoint is useful to
  humans and to the `/admin` surface later.
- Drift checks depend on GH cron reliability (acceptable: the same trust we
  extend to backups) and on the endpoint being reachable (uptime monitors
  already watch the API).
- The workflow file (`.github/workflows/ml-health.yml`) requires the
  `workflow`-scoped token to push — it ships as soon as the owner refreshes
  the token scope (same constraint as weekly-digest.yml).
