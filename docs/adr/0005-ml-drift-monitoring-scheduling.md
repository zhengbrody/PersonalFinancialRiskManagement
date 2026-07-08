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
Alerting lives server-side (structured log + Sentry `capture_message` when a
known status worsens, throttled by the cache), so the verdict is identical
whether a cron, a human, or an uptime probe asks.

## The statistical design (v2 — the naive version failed review)

The first draft compared the live 120-day window's PSI against the textbook
absolute bands (0.10/0.25) using the 15-year training MIXTURE as the
reference. Adversarial review **ran it**: 163/163 in-sample training slices
read "drift" — a measured **100% false-alarm rate**. A contiguous,
autocorrelated market window always occupies a narrow slice of a 15-year
mixture (that's what a regime IS), so raw PSI is large for every normal
window and the textbook bands (meant for i.i.d. scoring populations) are
meaningless here.

The shipped design is a **self-calibrated null**: training bakes into the
reference, per feature, the distribution of PSIs of every historical 120-day
training slice vs that same mixture (p50/p90/p99). Live status compares the
live window's PSI against its own feature's percentiles — `drift` means "the
current window is more unusual vs training than ~99% of all windows the model
was trained across", which is the question we actually want answered. Two
honesty consequences are accepted and documented: the expected false-alarm
rate is ~1% per feature by construction (≈ one watch/drift reading per feature
per ~100 trading days is NORMAL — hence watch is a look, not an action), and
KS is reported as a bare statistic with **no p-value** (an i.i.d. p on a
window with lag-1 autocorrelation ≈ 0.96+ would overstate significance by
orders of magnitude).

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
