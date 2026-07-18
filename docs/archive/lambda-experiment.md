# Archived: the Lambda micro-services experiment (Phase 2, 2026-05)

**Status: retired 2026-07-17.** The code was removed from the working tree —
recoverable from git history at any commit before this date (last living
tree: `git show 3d5f9c2:services/`). This page preserves the architecture
story; the interview-ready narrative lives in `docs/interview/stars.md`
(STAR #4: cross-arch Lambda images).

## What it was

A Phase-2 exploration of extracting compute-heavy paths out of the (then
Streamlit) monolith into containerized AWS Lambdas behind a REST API:

| Path (historical) | Purpose |
| --- | --- |
| `services/risk-calculator/` | Portfolio VaR/score compute as a Lambda |
| `services/options-pricer/` | Black-Scholes pricing + Greeks as a Lambda |
| `services/price-cache/` | yfinance price cache with TTL |
| `services/billing-webhook/` | Stripe webhook receiver |
| `libs/remote_compute.py` | The HTTP client the monolith would have used |
| `infra/infra/api_stack.py` | The CDK API-Gateway + Lambda stack |
| `.github/workflows/deploy-services.yml` | CI for the handlers + a deploy job permanently gated `if: false` |

## Why it was retired

- **Zero production consumers, ever.** `libs/remote_compute.py`'s only
  importer was its own unit test; the deploy job never ran (`if: ${{ false }}`
  since inception, waiting on an `AWS_DEPLOY_ROLE_ARN` secret that was never
  created).
- **The product went a different way.** The split-stack migration (ADR 0004)
  moved compute into the FastAPI backend on EC2; every capability the Lambdas
  prototyped now lives in `backend/app/services/` / `engine/` with tests.
- **It carried real CI noise**: `deploy-services.yml` triggered its test jobs
  on every `libs/**` PR (documented repeatedly in session logs as "the
  dormant Lambda workflow waking up").

## What was deliberately KEPT

- `infra/` (CDK stacks) — `compute_stack.py` bootstrapped the CURRENT
  production EC2 instance and documents the CloudWatch-Agent config
  (`MindMarket/EC2` namespace) that `scripts/cloudwatch-alarms.sh` binds to.
  `api_stack.py` stays as a historical record but is banner-marked
  NOT SYNTHESIZABLE (its Docker build contexts point at the removed
  `services/` sources — check out a pre-retirement commit to synth it);
  the whole directory is labeled historical in the README.
- `docs/aws/operations.md` — the CDK cookbook, banner-marked historical.
- `docs/interview/stars.md` — the career story (cross-arch image builds,
  Lambda cold-start findings).
