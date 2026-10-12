# Copilot Agent and ML operations — release status (2026-10-12)

This page is the single source of current state. Older plan and implementation
documents keep their dated history; where they disagree with this page, this
page wins. Every row below was checked against code, GitHub, the production
database and the running containers on 2026-10-12, not copied from earlier docs.

## Production at a glance

| Item | State |
| --- | --- |
| Running images | backend + frontend `sha-746de990a33c4274d639cbdf273c4bef57868d39` (Caddy unchanged, `caddy:2.11-alpine`) |
| Database migrations | 0001–0020 applied. 0014 and 0016–0020 were applied on 2026-10-12, in order, one transaction each, after a fresh encrypted backup (`db-backup` run 38222893195) |
| Signing key | unchanged (`MINDMARKET_RISK_RUN_SIGNING_SECRET`, 64 bytes). Every new record type derives a purpose-specific key from it, so evidence saved earlier still verifies |
| Regime model | trained 2026-10-12 (retrain PR #257), `/ml/health`: drift `healthy`, freshness `fresh`, approved artifact `match: true` (provenance) |

### Feature flags in production

| Flag | Value | Why |
| --- | --- | --- |
| `MINDMARKET_COMPARISON_REPLAY_ENABLED`, `MINDMARKET_COMPARISON_SAVE_ENABLED` | on | unchanged since September |
| `MINDMARKET_COPILOT_RUNS_ENABLED` + build `NEXT_PUBLIC_COPILOT_RUNS_ENABLED` | **on** (2026-10-12) | foreground run journal; not advisory |
| `MINDMARKET_PLAN_HISTORY_ENABLED` + build `NEXT_PUBLIC_PLAN_HISTORY_ENABLED` | **on** (2026-10-12) | reads the user's own saved plans; not advisory |
| `MINDMARKET_DECISION_SUPPORT_ENABLED` | off | proposes reducing specific holdings: personalised security suggestions. Stays off until the professional compliance review the design requires |
| `MINDMARKET_ASYNC_ANALYSIS_ENABLED` | off | only serves decision support |
| `MINDMARKET_CASH_SECURED_PUT_ENABLED` / `_SAVE_` | off | reached through the decision-support flow |
| `MINDMARKET_FUNDING_SCENARIOS_ENABLED` / `_SAVE_` | off | same |
| `MINDMARKET_JEV_INTENT_ENABLED` | off | experiment; no API key, effectiveness unverified |
| `PUBLIC_RISK_CHECK_ENABLED` | off | unchanged owner decision (data licensing) |

Rollback: run `deploy-ec2.yml` with the previous image sha, and switch flags off in
the EC2 `.env` (backend) or the repo variables (frontend; needs a rebuild). The
frontend image built with the two UI flags off is recorded as
`ghcr.io/zhengbrody/mindmarket-frontend@sha256:40fa0aec175ca3ac5310bbd68b0d1986dc631475fefbeecbc9020b56181d33c1`.
The migrations are additive. Rolling the code back leaves the new tables and
functions unused, not broken.

## Progress matrix

Legend: ✅ done · ⚠️ partial · ❌ not started · — not applicable.
"Enabled" means a production flag is on for all users.

| Item | Design | Code | Committed / merged | Tests (local + CI) | Prod migration | Deployed | Enabled | Live-verified |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Retrain delivered as a PR (respects branch protection) | ✅ | ✅ | ✅ #251 | ✅ | — | ✅ | ✅ | ⚠️ train, gates, branch push and tracking issue (#256) all ran for real; PR creation is blocked by a repo setting (see owner actions) |
| ML health: freshness + approved-artifact identity | ✅ | ✅ | ✅ #251 | ✅ | — | ✅ | ✅ | ✅ `fresh`, `match: true` |
| ML alert issues: per kind, deduplicated, close on recovery | ✅ | ✅ | ✅ #251 | ✅ | — | ✅ | ✅ | ✅ #252 opened and closed itself after recovery |
| Nightly real-login alert closes on recovery | ✅ | ✅ | ✅ #251 | ✅ | — | — | ✅ | ✅ #249 closed itself on 2026-10-11 |
| A/B task state, clarification, recovery | ✅ | ✅ | ✅ #254 | ✅ | ✅ | ✅ | ❌ off | ⚠️ background job path verified on prod DB via a non-public process (below) |
| B background jobs (durable queue, leases, one per owner) | ✅ | ✅ | ✅ #254 | ✅ real Supabase 13/13 | ✅ 0014/0016/0017/0020 | ✅ | ❌ off | ✅ on prod DB (non-public process) |
| C candidate comparison | ✅ | ✅ | ✅ #254 | ✅ | — | ✅ | ❌ off (compliance gate) | ✅ on prod DB (non-public process) |
| E cash-secured Put + funding + mixed-expiry ledger | ✅ | ✅ | ✅ #254 | ✅ independent oracles | ✅ 0018/0019 | ✅ | ❌ off | ⚠️ Put arithmetic on prod; the funding ledger is tested only locally |
| E broker buying-power / margin rules | ✅ interface | ⚠️ only the "unknown" provider | ✅ | ✅ | — | ✅ | — | — no broker connected |
| D research hypotheses | ✅ | ✅ | ✅ #254 | ✅ grounding eval 54/741 | — | ✅ | ❌ off | ❌ |
| F saved-plan history + versioned review | ✅ | ✅ | ✅ #254 | ✅ | — (reads 0015) | ✅ | ✅ | ✅ real login in CI (#255, nightly) and on prod DB |
| F offline continuous monitoring | ✅ design only | ❌ | — | — | — | — | ❌ | — |
| Jev intent adapter + bilingual eval set | ✅ | ✅ | ✅ #254 | ✅ contract tests | — | ✅ | ❌ off | ❌ needs API key |

### Production validation of the default-off features (2026-10-12)

A second backend process with the new flags on was started **inside** the backend
container, on `127.0.0.1:8001`. Caddy does not route to it and nothing outside
the container can reach it. Two dedicated throwaway accounts drove it against
the production database. All 19 checks passed:

- the job started and the HTTP call returned before computation finished (worker thread);
- a duplicate submission of the same id was idempotent, and a second active job for the same owner got 429;
- another user received 404 for the run (RLS);
- the run completed on the worker in 3.5 s with 2 candidates;
- the Put calculation returned results;
- a candidate was saved as a draft plan, and saving it again returned the same plan;
- history listed exactly that plan from a fresh session, with no client storage;
- another user saw no plans and got 404 on the evidence;
- the evidence was not shown under a different portfolio;
- the versioned review ran and did not attribute realised returns;
- the foreground journal accepted a run;
- both accounts were then deleted, cascading through their job rows.

The process was stopped afterwards, and no shadow process remains.

## What remains, and who owns it

Owner-only:
1. Repo setting **Settings → Actions → General → "Allow GitHub Actions to create and approve pull requests"**. Until it is on, each weekly retrain pushes a gated branch and opens or refreshes #256 instead of a PR. `ml-health` stays red on `train_pipeline`, which is accurate.
2. Professional compliance review before enabling decision support (C/E) for the public. Code readiness is not a substitute.
3. A Jev / TypeSafe decision (terms, US processing, retention) and an API key, before any real comparison. Also review the 148 provisional gold labels.

Engineering:
- Real broker rules (buying power, maintenance requirements). The only provider is "unknown", by design.
- Interest on cash deficits created by an earlier-date assignment is disclosed in the result, not modelled.
- Task-state supersession is enforced only once the newer version has *started*.
- The F offline monitor is design-only.
- Load, latency and provider-quota behaviour on the t3.micro has not been measured with real users.
