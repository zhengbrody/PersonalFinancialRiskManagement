# Copilot signed foreground runs — Phase 1B foundation

Date: 2026-09-06 Pacific. Branch: `codex/copilot-risk-check`.
Status: **local code, default OFF; migration 0014 NOT applied; NOT deployed**.
Parent: [Risk Agent plan](risk-agent-product-plan.md).

## Delivered, without another window

When enabled, Check my portfolio reserves a server record before calculation.
The browser saves its random run ID before POST. Refresh or switching the page /
floating Copilot leaves an interrupted turn with **Retrieve saved result**.
Retrieval only GETs the existing run (2.5-second polling while running); it never
restarts calculation. Browser waiting stops after two minutes and remains resumable.

**Stop waiting** aborts browser IO only. **Cancel server check** is explicit and
only reported as cancelled after the server confirms the state. Calculation
already executing may finish, but a cancelled run cannot publish that late result.
If completion won the race first, its completed result is returned instead.
Connection loss during cancellation means unconfirmed, not successfully cancelled.

The default, flag-off path remains the existing direct report check. No new page,
second input, holdings update, order, LLM credential access or scheduled task.

## Boundaries and provenance

| Module | Responsibility |
| --- | --- |
| `schemas/copilot_runs.py` | Closed states, UUID ownership, finite account inputs, timestamped typed results |
| `services/copilot_runs.py` | Caller-JWT repository, HMAC authentication, idempotent insert and conditional state transitions |
| `api/v1/copilot_runs.py` | Authenticated start/get/cancel; capture account inputs once; invoke existing report adapter |
| `api/v1/risk.py::compute_active_report` | Existing report computation without HTTP serialization; accepts captured context/profile; no duplicate engine |
| `lib/copilot-runs.ts` | Validated transport, run + portfolio identity checks, bounded polling |
| `lib/use-copilot-thread.ts` | One user/book timeline, stable run IDs, manual retrieval and cancellation |

The stored snapshot contains server-resolved holdings, cash, margin, contributed
capital, confirmed/neutral risk preference, history window, risk-free-rate and
market-shock parameters. Computation consumes that copied context/profile, not a
second active-book lookup. Inputs and results stay scoped to the original book.
Private holdings are stored only in the RLS-protected record, not returned by the
public run response or included in telemetry. No user prompt/JWT/secret is stored.

Canonical record **TEXT** is signed with independent HMAC-SHA256; TEXT avoids
PostgreSQL JSON numeric normalization changing the signed bytes. Identity, state,
input copy, timestamps, record version and result are authenticated together.
The indexed IDs/state must match the signed content. Invalid records fail closed.
Only an opaque machine error code is persisted; logs contain exception type only.
Each record is limited to 512,000 bytes.

RLS uses the verified caller JWT, with explicit `user_id` filters in repository
queries. No privileged database client is added. The owning client can still
write/delete its own rows via RLS: **HMAC authenticates engine provenance; it does
not make the table immutable or an audit ledger**. An owner can destroy or replay
their own previously signed record, but cannot forge a new signed result or move
it to another run/user/book. Do not use this journal as a privileged command or
exactly-once external action log. Database quota/retention controls and a user-facing
cross-device history/forget interface remain follow-up work before broad rollout.
Portfolio/account deletion cascades these records.

Duplicate IDs use `ON CONFLICT DO NOTHING`; legitimate simultaneous starts cannot
replace the original input or both compute it. Updates compare the previously read
signature and require state `running`. One non-queuing analysis lane is shared with
the direct risk check **per backend process**, not a distributed scheduling limit.
Runs expire after ten minutes when next read; a process crash does not trigger replay.
Storage failures never convert an unsaved result into a claimed durable completion.

This is **not** a background worker or multi-step planner. Tokens can expire before
completion is persisted; a failed final write leaves the run interrupted on expiry.
Market prices, snapshot history and model version artifacts are not fully captured
for deterministic re-execution. Same-snapshot candidate comparisons and confirmed
plan-saving provenance must wait for that separate work. Ordinary `/ask` still uses
its existing single-turn grounding path.

## Verification

- Full backend: **1,218 passed, 1 skipped; coverage 88.82%**. New run suite covers
  tampering, wrong identities, duplicate start, cancellation/completion races,
  expired runs after restart, result scope, feature disabled, capacity, frozen input
  use, sanitized failure logging and caller-JWT/query scoping.
- Frontend: **570 tests passed** across 115 files; recovery
  tests verify stable ID before POST, GET-only refresh recovery, polling cleanup,
  explicit server cancellation, wrong-run rejection and no false recovery offer
  when the server refused to start.
- Browser: **64 passed**, desktop Chromium + Pixel 7 emulation. New GET-only recovery
  flow passed in both. First attempt correctly rejected an incomplete test fixture
  missing `price_history_as_of`; fixture fixed without relaxing validation.
- Schema/core mypy, Black, Ruff, TypeScript, lint, Next production-like build and
  OpenAPI drift checks passed. Root engine suite previously passed 857 tests in 1A;
  no engine formulas changed during this continuation.
- Offline eval: **44 cases / 611 claims**, all structural checks pass. This is not
  live-model faithfulness; fixture failure-path warnings remain visible.
- **Not verified:** real PostgreSQL RLS or Docker image execution (local Docker
  daemon unavailable), real authenticated staging/provider/latency behavior, CI.

## Activation checklist — separate authorization required

1. Review `0014_copilot_runs.sql` and apply in a disposable/staging database using
   the normal transaction migration workflow. Verify with two actual authenticated
   users: owner CRUD; other-user SELECT/UPDATE/DELETE invisible; foreign-book INSERT
   denied; anonymous access denied; duplicate insert and cancellation CAS races.
   Also POST a tampered own-row and assert the API refuses its evidence.
2. Provision a **new independent random server secret of at least 32 bytes** as
   `MINDMARKET_RISK_RUN_SIGNING_SECRET`. Never reuse the Supabase JWT, service or share
   key, print it, commit it, put it in `NEXT_PUBLIC_*`, or send it to an LLM. Rotation
   invalidates existing records in this version; decide retention/migration first.
3. Set backend `MINDMARKET_COPILOT_RUNS_ENABLED=true` only after storage and key exist.
   `compose.split.yml` forwards these server settings; defaults stay off/empty.
4. Build the frontend with `NEXT_PUBLIC_COPILOT_RUNS_ENABLED=true` (GitHub repository
   variable → build-images argument → Dockerfile). It is a **build-time** flag:
   changing runtime environment alone cannot activate the browser transport.
5. Run authenticated equity/options/margin checks, cancel during actual compute,
   refresh during POST, edit/switch portfolios during the request, simulate storage
   failure/restart, check absence of private data in logs, measure cold/warm latency.
6. Obtain deployment approval. Rollback: disable the feature/revert the image;
   leave the additive table intact. Do not automatically drop stored private data.

References: [Python HMAC](https://docs.python.org/3/library/hmac.html),
[Supabase RLS](https://supabase.com/docs/guides/database/postgres/row-level-security).
Installed PostgREST Python `upsert` signature was inspected for
`ignore_duplicates=True` and representation return behavior; actual database
semantics remain subject to the staging checks above.
