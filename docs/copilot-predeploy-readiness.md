# Copilot deployment-readiness verification

> **Current state lives in [release status 2026-10-12](copilot-release-status-2026-10.md).** Migrations 0014–0020 are in production; the run journal and saved-plan history are enabled; decision support, background jobs, Put and funding scenarios are deployed but off (compliance gate). The text below is the dated history.

This package prepares local evidence before deployment validation. It does not
apply hosted migrations, deploy builds, switch production flags, call a broker,
train a model or authorize orders. A green local suite is not release approval.

## Run the local matrix

Use the project's working Python environment (on the current development host,
`/opt/anaconda3/bin/python`). From the decision-support worktree:

```sh
python scripts/run_copilot_predeploy_checks.py
python scripts/run_copilot_predeploy_checks.py --run backend typing format frontend typescript lint eval browser
python scripts/run_copilot_predeploy_checks.py --run auth_migrations
python scripts/run_copilot_predeploy_checks.py --run auth_migrations --soak-repeats 3
```

The default prints a plan without running commands. JSON rows explicitly report
`passed`, `skipped` or `blocked`. Exit code reflects selected local checks only;
external blockers remain in the report even when exit code is zero. A passed
pytest command may include test-level skips; it does not mean optional database
checks ran. Select `auth_migrations` for real local Auth/PostgREST and migrations.
Child output is discarded rather than printed or persisted because even local
CLI diagnostics can contain credentials. To diagnose a failure, run its named
command separately in the intended development environment.

The allowlisted matrix includes backend coverage (85% minimum), schema/core
mypy, Black, frontend unit tests/typecheck/lint, offline grounding evaluation,
and the desktop/mobile Put and funding Playwright cases. It does not claim
whole-application mypy cleanliness or substitute fixture evaluation for live
model quality. Test/build tools may create ordinary local artifacts; the wrapper
never edits application configuration or production feature flags.

`auth_migrations` invokes the existing isolated acceptance harness. It refuses a
linked Supabase project and remote Docker, owns only the fixed local staging
project, binds its exposed ports to loopback and stops only its containers in a
`finally` block. Development JWTs are transient in the existing test process;
this wrapper never reads, writes or serializes JWTs or secret files. Existing
acceptance covers real login/RLS, signed confirmation, idempotency, process loss
and genuine lease expiry, concurrent instances and durable queue overflow.

The repeat option accepts only 1–5 full isolated suite runs and stops on the first
failure. This is bounded repeated synthetic acceptance, not a production soak or
a latency percentile claim. There is deliberately no outer force-kill deadline
around Auth: it must reach its owned-container cleanup. Each harness operation
has its existing startup/poll deadlines. Do not launch another copy against the
same dedicated staging project while it runs. Do not stop unrelated containers.

## Prepare generated contracts and migration evidence

Before running the matrix, maintainers regenerate contracts in a reviewed local
checkout and inspect the diff:

```sh
python scripts/export_openapi.py
npm --prefix frontend run gen:api
git diff --check
git diff -- openapi.json frontend/src/lib/api-types.ts
```

These are preparation commands, not silently run by the verification wrapper.
The local Auth suite applies the needed existing migrations, including job
transitions/recovery and immutable Put confirmations. It does not apply any
migration to a hosted service. For a release, inventory the actual migration
head in the target and rehearse forward application and rollback policy against
an isolated copy; never infer readiness from matching migration filenames alone.

## Architecture and release boundaries

- Job transitions compare the old signature under a database row lock, enforce
  revision increments and use database-clock lease fencing. The job schema and
  confirmation signatures are independent of an in-memory queue.
- Authentication remains user-scoped and transient. Restart recovery needs fresh
  user authentication; there is no privileged credential sweeper or persisted JWT.
- Calculation receipts bind implementation fingerprints. New first-time saves
  reject changed implementations; authenticated original saved Put evidence can
  still be read, and review identifies implementation changes.
- New jobs capture an execution implementation fingerprint. Claim and compute
  reject missing or changed fingerprints with `execution_version_changed`; old
  signed records remain parseable but cannot silently resume through changed
  code. The user must start a fresh calculation. Actual old/new release artifacts
  and compatibility behavior must still be tested as a release pair.
- Every serving process must retain the same signing-key lineage. No automatic
  key-ring migration exists; changing the root key invalidates old evidence.
- Capacity limits are per application process. Local two-instance tests are not
  a global cluster-wide admission-control guarantee.
- Put history is authenticated, cursor-paged original evidence. Periodic review
  is opt-in for the current visible logged-in session and the first 20 loaded
  plans. It does not perform unattended monitoring, fetch live quotes, execute
  trades or attribute realised returns.

## Blockers intentionally retained for deployment validation

| Gate | Evidence still required |
| --- | --- |
| Actual release-pair rollout | Named old/new immutable artifacts, record readability, version-change rejection, shared-key continuity, drain/restart and rollback against the intended migration sequence |
| Sustained production workload | Representative portfolios and provider responses, resource limits, rate limiting, memory/CPU, cancellation behavior and measured latency/errors over an agreed duration |
| Live provider and broker coverage | Authorized provider access, quotes/settlement freshness, permissions, house margin and option contract rules; synthetic cases cannot prove these |
| Public personalized advice | Service-specific professional compliance assessment and rollout decision |

Until these gates have real evidence, do not describe the system as deployed,
broker-approved, universally margin-capable or fully validated under production
load. No disclaimer, passing local suite or model fine-tuning substitutes for
those checks.


## Local acceptance checkpoint — 2026-09-19

The optional common-expiry whole-account ledger is now integrated with the
funding request, response, signed confirmation/replay and the existing Copilot
editor. Real local Auth/PostgREST acceptance passed 12 tests, including the new
ledger save/read assertions, process recovery, duplicate submission and RLS.
This run used only the dedicated staging stack and stopped its containers.

Backend regression: 1,560 passed, 36 skipped; coverage 88.81% against the
85% backend gate. Schema/core mypy passed for 52 files. The offline grounding
evaluation passed 50 cases and 722 assertions. Optional test skips are not
reported as executed acceptance. Frontend regression passed 647 tests; the
production build and all 10 desktop/mobile Copilot Playwright cases passed.
The mobile composer now stays in document flow so expanded scenario forms do
not have their confirmation controls obscured.

The ledger's independent closed-form tests and isolated guard mutations cover
initial option liabilities, existing physical assignment in the baseline,
sold-stock opportunity cost, fees, unknown APR, interest and nonpositive equity.
Additional endpoint and signed-replay tests reject missing prices and modified
or omitted ledger outcomes. Frontend guard mutations reject account mismatch
and invalid-input submission. These are deterministic engineering checks, not
validation of forecast accuracy or live broker terms.

Remaining engineering beyond this common-expiry release candidate includes
residual option valuation for mixed expiries, protection/exercise dependencies,
and objective-specific conditional ranking once its complete risk inputs and
rules are defined. The original broad C/E roadmap remains larger than this
implemented and tested slice. No model training or new live data subscription
was performed. Python/NumPy/SciPy and TypeScript remain the implementation stack;
adding C++ or Java is deferred until profiling demonstrates a specific need.
