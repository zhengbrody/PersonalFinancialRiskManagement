# Copilot decision support — implementation status

User authorized execution on 2026-09-11. Implemented on
`codex/copilot-decision-support`, based on local main `11a0698`, in an isolated
worktree. Original working-tree marketing assets and export script were untouched.

This is a **local, default-off A/B/C slice**, plus the initial D method cards.
It is not completion of the full A–F design and is not a production release.

## Delivered behavior

- `/ask` has an additive typed `decision_support` field. The new route separates
  supported general concepts, clarification, user-specified comparison and
  candidate requests. Supported concepts receive deterministic explanations even
  without an account. User assumptions are never promoted to confirmed constraints.
  The existing six sections and ordinary router/grounding checks remain available.
- Four reviewed, versioned method cards describe downside, valuation, systematic
  construction and cash-secured puts. Paraphrases, checks, counterpoints, scope,
  author, URL and review date are separate from account evidence. There is no
  runtime crawler, external instruction execution or unrestricted LLM advice.
- A same-window form confirms an amount, cash-versus-debt goal and protected
  holdings. The first candidate search examines up to two eligible stock/ETF
  reductions, selected by positive historical covariance contribution. It excludes
  protected holdings, cash-equivalent buffers and underlyings of existing options.
  All alternatives use one captured account, one price frame and one option capture.
- The existing comparison service supplies account math, stresses and limitations.
  A conditional preference is issued only for an alternative that is no worse in
  all compared risk dimensions and strictly better in at least one against both
  no action and the other candidate. Mixed books are not given a synthetic scalar
  ranking. No feasible candidate is a valid, explicit result.
- Each evaluated alternative can receive the existing signed replay/save receipt.
  Confirmation uses the existing RiskPlan endpoint, portfolio revision guard,
  idempotency and fifteen-minute capture window. It saves the selected assumption
  and original calculation, not the batch's judgment or an order.
- The numerical badge now says values were checked against sources; it does not
  imply that all prose and investment conclusions have been proven correct.

## Background execution and deliberately bounded recovery

`/copilot/decision-runs` uses version-two records in the **existing** `copilot_runs`
 table, shared HMAC codec and owner-scoped store. Migration 0016 extends 0014 and
adds a SECURITY INVOKER transition RPC. The old foreground runs are unchanged.

One daemon worker per backend process shares the existing analysis semaphore.
At most four dispatches are retained in memory. Persist-before-dispatch means
queue saturation or a process crash leaves a visible `queued` record. Duplicate
run IDs never replace the original constraints. Only a successful signature CAS
can claim a task. Completion is fenced by the original revision and the server
clock's lease check. Cancellation suppresses publication, not Python execution.

Migration 0017 adds renewable two-minute leases with a fixed **five-minute
execution deadline per attempt**. Heartbeats reverify the transient user JWT and
CAS the signed revision; database time rejects expired publication and extending
the deadline. There are at most two attempts. Capturing/evaluating are actual
capture boundaries, not fabricated reasoning steps. Cancellation and shutdown
fence publication; Python computation itself is not forcibly preempted.

The app lifespan owns its dispatcher and drops queued in-memory credentials on
shutdown. After each dispatch it can recover pending records for that same user
and portfolio while the current JWT remains valid. After restart or token expiry,
the user must authenticate again and explicitly request recovery. Recovery can
recompute with fresh prices. There is no privileged sweeper, durable JWT or
unattended recovery after restart.

Authenticated recent-run listing scans at most 40 rows and returns at most 20
verified unexpired version-two records. The same-window recovery panel appears
after the server advertises candidate support, including in a restored
conversation; it uses the current login and resets when the account/portfolio
changes. GET lists and updates expired state but never dispatches calculations.
Listing is bounded and is not an exhaustive archive.

Results remain visible for one day. Explicit recovery also removes at most 100
old version-two rows for the authenticated owner and requested portfolio, using
a SECURITY INVOKER cleanup RPC and database creation time. Legacy version-one
records remain untouched. This is opportunistic cleanup, not a global retention
scheduler. Deployment restart/soak tests, fully authenticated worker computation
and representative P50/P95 measurements remain B follow-up; **B is not complete**.

## Validation

- Backend full suite: 1411 passed, 18 skipped, coverage 88.49% at the recorded run.
  A subsequent focused suite ran 33 tests successfully, including the five real
  PostgreSQL checks; later worker and batch-binding regressions also passed.
- New database tests: five **actual isolated PostgreSQL** checks passed, covering
  CAS, server-clock expiry, RLS isolation, cancellation and live-lease reclamation.
  They are opt-in and counted as skips in the full suite above, not double-counted.
- Frontend: 599 tests passed; TypeScript, lint and production build passed.
- Existing offline grounding eval: 50 cases, 722/722 assertions. This checks the
  legacy default-off route; it is not an accuracy claim about live model advice.
- New desktop and Pixel 7 Playwright checks passed: confirm constraints, calculate,
  inspect result, reload and retrieve without recomputation; one chat input and
  no horizontal overflow. These use synthetic API fixtures, not real login.
- Source inspections and read-only web verification supported the method cards.
  No full articles or author personas were copied.
- Five legacy endpoint tests aged out against fixed September price fixtures.
  Their endpoint clock is now fixed to the fixture date; production freshness
  enforcement remains intact. All 93 affected comparison/replay tests passed.
- Mutation checks cover confirmation, protected holdings, liquidity buffers,
  claim CAS, HMAC rejection and the database lease predicate. An initially non-discriminating liquidity test was
  replaced with positively correlated prices so deleting the guard is detected.

## Enablement and remaining scope

`MINDMARKET_DECISION_SUPPORT_ENABLED=false` and
`MINDMARKET_ASYNC_ANALYSIS_ENABLED=false` are the defaults and are forwarded by
`compose.split.yml`. No new frontend build-time flag is required: the server
advertises whether the candidate form is available. Existing stored job reads
and cancellations stay available after new-job disablement, subject to auth/key.

Production activation has **not** been performed. It needs reviewed 0014/0016/0017
application, an independent run signing key, authenticated end-to-end acceptance,
worker/deployment lifecycle acceptance, representative latency checks and the
professional review identified in the design for public personalised suggestions.
Local SQL tests do not substitute for that evidence.

Still outside this slice: free-form multi-turn task state, independent resumable tool steps,
Research retrieval/claim linking, new hypothetical option legs, assignment and
broker buying-power calculations, option strategy modification, cross-time
versioned review and scheduled monitoring. E and the new parts of F are not
implemented. Existing user-confirmed comparison/save functionality is reused.

The first sell-Put question now leads to a scoped funding comparison. It does
**not yet** answer whether a new put is affordable or suitable after assignment.
Do not present this slice as the complete sell-Put decision loop.


## Data and training status (2026-09-11)

Four curated original-source method cards are integrated into response routing.
No new live market data feed, external research retrieval, training dataset,
model training or fine-tuning has been added. Existing account and price capture
and deterministic risk calculations remain the numerical authority. Test runs
are engineering verification, not training or evidence of investment returns.

## Reliability follow-up validation

- 15 focused job tests passed, including malformed stored documents, signature
  rejection, bounded renewal, credential disposal and recovery.
- 9 isolated PostgreSQL checks passed, including immutable deadlines, null/overlong
  lease rejection and bounded owner-scoped cleanup preserving legacy records.
- Frontend 601 tests passed; TypeScript, lint and production build passed.
- Required backend mypy gate passed for all 46 schema/core files. An exploratory
  whole-app check with the root configuration is not clean (213 errors); that is
  outside the existing backend gate and is not represented as a passing check.
- Backend CI command: 1424 passed, 23 skipped, coverage 88.63% (85% gate).
  The earlier run inherited legacy root coverage settings; the CI-configured
  rerun above is the applicable backend gate.
- Actual isolated Supabase Auth/PostgREST: 5 checks passed, including new job
  claim/renew/list/cancel/cleanup using a real password-login JWT. Calculation is
  not exercised by this auth check; worker computation still needs integrated
  authenticated acceptance. Two fixture setup issues (required user fields and
  reapplying table creation) were corrected before the successful run.
- Desktop and Pixel 7 browser checks both passed for the candidate/retrieval
  flow plus explicit recent-list and recovery actions, using synthetic APIs.
- Removing the SQL deadline-immutability guard caused the targeted test to fail;
  the exact migration was restored and all 9 database checks passed again.
- Dedicated local Supabase containers were stopped after acceptance; no hosted
  database, production account or production application was modified.


## D follow-up: bounded Research context (2026-09-12)

Behind the existing default-off decision-support flag, ticker research now reuses
the cached FactPack once per ticker (at most three for a comparison, within the
existing tool budget). No new provider subscription, crawler, external page fetch
or model training is introduced.

The existing Copilot answer carries typed company observations for P/E, net margin,
debt/equity and revenue CAGR. Each observation binds ticker, metric, unit, source
block and provider timestamp. No financial reporting period is invented. The
current FactPack cannot establish exact field-level origin when providers are
mixed; this limitation is explicit. Timestamp freshness means a provider snapshot
within one day, not freshness of the financial reporting period.

Only finite, dated observations from recognized provider blocks enter numerical
evidence. Missing/unknown/future timestamps, stale cache and mismatched tickers
cannot promote research into directional model output. Question cards link to
observation identifiers, with counterpoints and falsification checks based on the
existing valuation/downside method cards. They are explicitly untested hypotheses,
not bull/bear conclusions or evidence that an investment is suitable.

Up to three deduplicated HTTPS news links are displayed as unverified metadata.
No article body is retrieved; missing author/conflict details remain unknown.
News titles, ratings, drivers and arbitrary provider prose do not enter the new
numerical evidence or LLM prompt. These links cannot authorize tool execution,
change candidate ranking, save a plan or modify the account.

The panel stays in the same conversation and is compatible with old saved
answers that have no research context. Ordinary ticker comparisons now bypass
the reduction-confirmation route; explicit reduction comparisons retain it.

Remaining D work: licensed document retrieval, exact filing/period provenance,
verified claim-level citations, author/conflict/opposing-source verification,
and account-specific thesis evaluation. This is not completion of the full D/E/F
roadmap or the initial complete put-assignment acceptance scenario. No independent
training dataset or fine-tuning job has been created.

D validation:
- Full backend CI suite: 1446 passed, 23 skipped, 88.72% coverage. Skipped
  opt-in integration checks were not run for this read-only projection change.
- After the final CAGR source-label correction, 34 focused routing/research
  checks passed; required mypy passed for 47 schema/core files.
- Frontend 604 tests and TypeScript passed after the final schema change.
  Production Next build and desktop/mobile Research checks passed; the combined
  candidate/research browser suite also passed all four checks.
- An initial desktop candidate test filled the input before portfolio hydration
  remounted it. Waiting for the loaded portfolio fixed the test setup; production
  account-scope reset behavior remains unchanged.
- Existing offline grounding evaluation: 50 cases, 722/722 assertions. This is
  regression evidence, not model training or an investment-performance claim.
- Seven mutation checks detected removed ticker/freshness/evidence/HTTPS/
  external-prose/reference/derived-source guards. Exact files were restored.
- Black checked the full repository; Ruff and the backend trust-boundary mypy
  gate passed. Browser screenshots were inspected, including the mobile layout.
- No live provider call, hosted database migration, deployment or paid training
  job was performed. The implementation branch remains default-off.
