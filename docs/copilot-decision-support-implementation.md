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
versioned review and scheduled monitoring. The initial E cash-secured-put slice is recorded below; leveraged/combined
option scenarios and the new parts of F remain unimplemented. Existing user-confirmed comparison/save functionality is reused.

The first sell-Put question now leads to a scoped funding comparison. The first E slice below adds conditional cash-funding arithmetic for a standard
new put. It does not establish suitability or support financing/combined positions.
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


## E follow-up: hypothetical cash-secured Put (2026-09-12)

The existing conversation conditionally exposes a structured Put form.
POST /api/v1/copilot/cash-secured-put is authenticated and read-only. Both
MINDMARKET_DECISION_SUPPORT_ENABLED and MINDMARKET_CASH_SECURED_PUT_ENABLED
must be true; both default off, including Compose forwarding. No migration,
quote subscription, order, stored job or plan-save capability is added.

Inputs are user-confirmed hypothetical underlying, expiry, spot, strike,
per-share premium, whole contracts, total estimated fees, other cash holds and
cash buffer. Separate confirmations establish standard unadjusted USD 100-share
physical delivery and that recorded cash is gross settled USD cash BEFORE holds.
The app cannot independently verify settlement, open orders or contract listing.

The initial supported account has zero financing debt, identified nonnegative
USD cash/stock/ETF positions and, optionally, fully described existing short puts.
Unconfirmed, adjusted, near-expiry or other option legs stop the funding
calculation. Long options may create exercise/delivery obligations; their
protection is never removed or silently credited as available collateral.
Non-USD assets, short securities and unsupported asset types also stop it.

- Full assignment payment = strike × contracts × 100.
- Existing short puts reserve their full strike payment without hedge offsets;
  those reserves remain locked across displayed scenarios. Other cash holds and
  the requested buffer are additional deductions. Treasury ETFs are not cash.
- Coverage requires full strike funding BEFORE new premium. A premium receipt
  cannot hide a pre-trade shortfall. Coverage is conditional arithmetic, never
  a broker buying-power or suitability claim.
- Reuses options_strategies.build_strategies for exact expiry risk bounds and
  options_analytics intrinsic value for the scenario ledger. Net premium, fees,
  worst loss at zero, break-even and assignment cash are shown.
- At entry, the assumed option liability offsets premium received; initial
  incremental equity is minus fees. Premium is not immediate profit.
- Each expiry row compares incremental P&L with zero for no new trade and shows
  shares acquired, settlement cash, cash after retained reserves and funding gap.
  Below-strike rows assume assignment; actual early/at-expiry exercise can differ.
- Captured account identity/data are checked again before response. Changing
  assumptions clears the frontend result and all confirmations. Nothing is saved.

The formulas and assignment caveats were checked against the public
[OIC cash-secured-put guide](https://www.optionseducation.org/strategies/all-strategies/cash-secured-put)
on 2026-09-12. No article body is stored or provided to a model. The new service
does not call a market provider or LLM.

Remaining E scope: verified executable quotes/contracts, brokerage-specific
collateral/settlement rules, leveraged funding, combined protection legs,
exercise-event handling, existing holdings' scenario P&L and account concentration.
The user's full “sell holdings then fund puts using margin” acceptance case is
still not complete. The initial F implementation below adds confirmed original saving and manual assumption review. Automatic monitoring and realised-outcome attribution remain outside scope.

E validation:
- Backend CI suite: 1473 passed, 23 skipped, coverage 88.81%; opt-in external
  integration checks were not run for this deterministic foreground addition.
- 27 Put checks passed after restoring eight verified mutations: consent,
  pre-premium funding, existing collateral, entry equity, fee-inclusive loss,
  other option obligations, final account binding and contract scaling.
- Frontend 606 tests and TypeScript passed; lint and production Next build passed.
  Desktop/mobile Put and candidate flows passed all four tests; after improving
  fractional break-even display, the two Put browser checks passed again.
- Required backend mypy: 48 schema/core files passed. Black checked all 425 Python
  files; Ruff passed. Compose parsed successfully with the new flag default off.
- Existing offline eval: 50 cases, 722/722 assertions, not training.
- The mobile result screenshot was inspected. Synthetic tests use supplied
  assumptions, never real broker orders or personal portfolio data.
- No live quote execution, database write, deployment or model training occurred.


## F follow-up: confirmed Put plans and manual review (2026-09-12)

MINDMARKET_CASH_SECURED_PUT_SAVE_ENABLED defaults off. When enabled with the
independent run-signing secret and migration 0018, new Put calculations receive
a purpose-separated HMAC receipt containing the original account, assumptions,
result, capture time, account revision and implementation fingerprint. The
receipt is not permission to save or trade.

A separate explicit confirmation creates a draft in existing RiskPlan storage,
with evidence in the existing immutable comparison_confirmations table.
Migration 0018 adds a Put-specific SECURITY INVOKER transaction using the existing
owner locks, RLS and revision trigger from 0015. No parallel table is introduced.
A new save must be within fifteen minutes, match the account revision and active
portfolio, use the same implementation and reproduce the exact original result.
The transaction makes retries idempotent. An uncertain response tells the user
to retry the same calculation; a previously committed result remains retrievable
even after account changes or expiration of its original save window.

Historical reads authenticate original bytes and bindings without recomputing
under today's code. Editable RiskPlan notes/impact are never the source of the
verified result. The original inputs, funding figures, calculation time and
limitations are displayed inside the existing Copilot. Bounded history inspects
at most forty owner/portfolio confirmation rows and returns at most twenty
verified Put records; it is not a paginated or exhaustive archive. Legacy
comparisons and unverifiable records are omitted. There is no global scan.

Manual review reads current authenticated account data and checks scope/revision
again before responding. It reports changed holdings, cash, debt, capital,
revision, implementation or expiry status. It always requires either a new
calculation or renewed confirmation of assumptions: unchanged account data does
not verify a live premium, settled-cash status, open orders or suitability.
Reviews do not mark a trade as executed, infer realised returns, change holdings
or replace the signed original. Review results are shown with their timestamp;
they are not persisted as an automatic monitoring history.

RiskPlan's ordinary Health Score review is not used for these calculations;
the panel points back to Copilot's authenticated original and assumption review.

Validation:
- Backend CI: 1481 passed, 27 skipped, coverage 88.69%. Opt-in skips were kept
  separate from the explicit integration runs below.
- Eight save/review unit/API checks and three actual isolated PostgreSQL checks
  passed after restoring seven mutations (receipt integrity, age, implementation,
  replay, revision-only changes, SQL clock and SQL revision guards).
- Six actual local Supabase Auth/PostgREST acceptance checks passed, including
  Put capture, confirmed save, retry, list, cross-owner isolation, mutable draft
  edits and changed-cash review. Dedicated containers were stopped afterward.
- Frontend 608 tests, TypeScript, lint and production Next build passed. Desktop
  and mobile covered confirmation, saved input inspection, retrieval and review;
  the mobile saved-plan screenshot was inspected.
- Required mypy passed for 49 schema/core files; Black checked all 429 Python
  files; Ruff passed. Existing offline eval passed 50 cases, 722/722 assertions.
- No production migration, deployment, order or model training occurred.

Remaining roadmap: production enablement and deployment/soak acceptance, exhaustive
history/pagination, verified live quote and broker integrations, financed/combined
option scenarios, and scheduled review/outcome attribution. The full original
margin-funded Put decision loop and full A–F roadmap remain incomplete.

## 2026-09-13 — Authenticated worker calculation acceptance

Extended the dedicated local Supabase suite from six to eight checks. The new
parameterized HTTP scenario executes both normal submission and authenticated
recovery of a persisted queued record that was never submitted to a process
queue. Both paths use real Auth, JWT-scoped PostgREST/RLS, application lifespan,
dispatcher, lease journal, risk calculations and signed comparison confirmation.
Only daily market prices are replaced with a deterministic SPY fixture in a
separate test-only ASGI entrypoint; production startup has no test switch.
The local harness now installs the required 0009 preference migration and builds
recovery snapshots with the same authenticated account resolver as production.

Assertions cover completion in one attempt, matching no-action baseline,
candidate cash, replay receipt confirmation, identical results on duplicate
submission, cross-user read denial, and unchanged holdings/cash/debt/revision.
A subsequent Put calculation must use the original recorded cash (1,000), not
hypothetical candidate cash (1,500), and retain its 10,000 funding gap with the
fixture's requested cash buffer. Existing Put save/retrieve/review checks remain
part of this same local suite.

Validation: all eight local Supabase acceptance cases passed (9.38s test time,
excluding container startup); 53 focused worker/candidate/Put regression tests
passed. Black, Ruff and diff whitespace checks passed. No frontend or production
calculation code changed, so previous full-stack results above are historical,
not newly rerun here. The runner stops only its dedicated local containers.

This validates persisted-queue recovery, not a forced process crash during an
active calculation. Live deployment restart/lease-expiry recovery, soak/load
acceptance and provider latency remain open. Features remain disabled by default;
no production migration, deployment, new data feed or model training was done.

## 2026-09-13 — Running-process crash and lease-expiry acceptance

The dedicated local Supabase harness can now SIGKILL and relaunch only its own
ASGI subprocess. A test-only market barrier pauses a real dispatched calculation
after the persisted `capturing` step. The application is killed without graceful
shutdown and restarted using the same signing key, database and application
version. Production lease duration (120 seconds) and both application/database
clocks remain unchanged; no signed records or timestamps are edited to expedite
the test.

The new acceptance case verifies that recovery cannot dispatch while the old
lease remains valid; expiry exposes an interrupted record with no result;
unauthenticated recovery is denied; authenticated recovery completes on attempt
two; a publication using the first attempt's stale revision cannot overwrite the
completed result; and subsequent recovery dispatches nothing and retains the
identical final result. Daily SPY prices remain synthetic, while Auth, RLS,
journal CAS, process lifecycle and risk calculation are real.

Validation: nine local Supabase cases passed in 131.26 seconds, including the
actual lease wait; 53 focused worker/candidate/Put regressions passed. Black,
Ruff and whitespace checks passed. Only acceptance harness/tests and this record
changed; no production behavior, feature flags, database or deployment changed.

B now has local evidence for both lost-queue and running-process crash recovery.
Remaining release work includes version-changing/rolling deployment compatibility,
signing-key continuity operations, multiple application instances, sustained load
and live-provider latency. This same-version local process restart does not close
those production acceptance items or the broader C/E financing scenario roadmap.

## 2026-09-14 — Two-instance contention and queue overflow acceptance

The isolated acceptance harness now starts a second owned application subprocess
on a separate loopback port with the same local database and signing key. Both
processes execute the real dispatcher, JWT/RLS requests and journal transitions.
The synthetic market adapter records only process IDs in a fixture-owned file so
assertions count actual market captures, not just final states.

Two additional acceptance cases passed:
- Three rounds of eight concurrent submissions of the same run ID, split across
  both processes. While market capture is held, recovery on either process cannot
  dispatch the leased job. Each round has exactly one capture and one attempt;
  both processes return the identical completed result on subsequent submission.
- Twelve distinct simultaneous jobs exceed the two processes' combined eight
  in-memory dispatch slots. All twelve remain visible in durable storage while
  capture is held. After release they drain without another explicit recovery
  request, with twelve distinct results, one attempt and one capture per job.

Validation: all eleven real local Supabase acceptance cases passed in 145.19s,
including the unchanged real lease-expiry crash test. Sixty targeted worker,
comparison replay/save and Put-plan regressions passed, including version drift
and key-change rejection. Black, Ruff and whitespace checks passed. Only test
harness code and documentation changed; production flags remain unchanged.

Release compatibility boundaries:
- All serving processes must share the existing signing key. There is no key-ring
  migration implemented here; changing the key makes older signatures unverifiable.
- A calculation implementation fingerprint change requires a fresh calculation
  before first confirmation. Saved Put history remains readable and its manual
  review flags implementation changes; it is not silently recomputed as history.
- These processes used the same application version. Actual mixed-version rolling
  deployment, signed-record schema compatibility and rollback must still be
  checked against the specific release pair before enabling that rollout.
- This is bounded contention/burst acceptance with synthetic prices, not a soak,
  production capacity claim or live-provider latency measurement. Queue limits
  are per process; this does not introduce a global multi-instance resource cap.

The local B acceptance now covers lost queue, active-process crash/expiry,
multiple-instance claim contention and durable queue overflow. Sustained load,
release-pair deployment acceptance and the full C/E financing scenario remain open.

## 2026-10-11 — A/B: multi-turn task state, clarification and recovery

### Audit (state before this change, base `91b35f0`)

- **Classification is per message and stateless.** `decision_support.classify_task`
  (`backend/app/services/decision_support.py:66-105`) maps ONE message to
  `explanation / clarification / specified_comparison / candidate_request` and a
  fixed `missing_inputs` list (`:56-63`: goal/budget/protected_holdings, Put
  terms, broker rules, APR). `describe_task` (`:108-198`) turns that into prose.
- **What it asks for** is prose only; no value from the message was ever kept.
  `DecisionTask.confirmed_constraints` (`schemas/decision_support.py:15-16`) existed
  but nothing populated it.
- **Where clarification answers were kept: nowhere.** `copilot_router.answer`
  (`services/copilot_router.py:1749-1810`) handled each `/ask` independently;
  `CopilotAskRequest` (`schemas/copilot2.py:97-106`) had no task context; the
  endpoint cache key (`api/v1/copilot.py:207-212`) was message-only. A follow-up
  ("keep NVDA") was routed as a brand-new question and usually fell through to
  the generic router — the same window did NOT continue the task.
- **Typed constraints lived only in browser memory.** `CopilotCandidates`
  (`frontend/src/components/copilot-candidates.tsx:16-19`) held goal/amount/
  protected in React state (lost on reload); only the run id was persisted
  (`:26-31`). The form was re-rendered under every qualifying turn.
- **Confirmed parameters = the run record.** `/decision-runs` start
  (`api/v1/copilot_jobs.py:63-102`) required `task.confirmed` (StrictBool) and
  stored the immutable `CandidateRequest` in the signed v2 record
  (`schemas/copilot_jobs.py:62-68`); a different task under the same id → 409
  (`services/copilot_jobs.py:245`). There was no version concept across edits.
- **Account data** is captured server-side at reservation (`RunSnapshot`,
  `api/v1/copilot_jobs.py:85-95`) and the worker re-checks the portfolio revision
  before and after computing (`services/copilot_jobs.py:396-445`).
- **Background execution** already ran on a daemon worker thread
  (`Dispatcher.submit`, `services/copilot_jobs.py:535-554`), but no test proved
  the HTTP response precedes the computation (existing tests mocked `submit`).

### Implemented

Typed task state (`schemas/copilot_task_state.py`, `services/copilot_task_state.py`)
with three strictly separate parts:

| Part | Source | Trust |
| --- | --- | --- |
| `assumptions` (goal, amount, protected_holdings + turn stated) | parsed from the user's own chat message by fixed rules | prefill only; never a parameter, never consent |
| `confirmed` (version, goal, amount, protected, run_id, stale) | `POST /copilot/task-state/confirm` from the typed form with `confirmed: true` | versioned; new parameters → version+1, previous run superseded |
| account data | `RunSnapshot` captured server-side from the authenticated active portfolio | unchanged; never from client text |

Storage: no new table. The record is an HMAC-signed token (existing
`signed_plan_records`, domain `copilot-task`, purpose `state`, same root secret,
8 KB cap) held in the client's user+portfolio session partition and echoed back.
The server verifies signature, owner, portfolio and expiry on every use; a bad,
foreign-user or other-portfolio token on `/ask` is *discarded* (never blocks the
question). Durable confirmed inputs remain the v2 run record in `copilot_runs`.

Follow-up decision (deterministic; no LLM): `follow_up()` →
`continued` (≥1 slot parsed unambiguously; merged as assumption) · `ambiguous`
(percent, multiple amounts, bare number when amount wasn't asked, cash+margin,
buying power, negation, keep-without-ticker, ticker-without-keep → asks a fixed
question, changes nothing) · `unrelated` (no slot, or a different task kind such
as an explanation / Put / Test a change → normal router, task kept) ·
`turn_limit` (max 3 chat clarifications, then the form) · `closed` (cancel) ·
`expired` (30 min idle, 2 h cap; confirmed tasks live 1 day like their run).
Amounts require an explicit currency anchor unless the pending question is the
amount AND the message is only a number. Confirmed parameters are never changed
by chat. Research/news text never reaches the extractor (only `body.message`).
Follow-up replies are deterministic and echo no user figure in prose; the typed
panel shows assumptions labelled "not confirmed".

Start binding: `StartCandidateRun.task_state` (optional, additive). When given,
the run id and parameters must equal the current, non-stale confirmed version
(`task_state_mismatch` otherwise, nothing reserved).

Supersession (server-side, 2026-10-12): the token is stateless, so a version-1
token keeps verifying after version 2 is confirmed. A run started with a
`task_state` therefore records `task_id` + `task_version` inside its signed v2
job record (optional, additive fields; legacy records carry `null`). Before any
start, task resume or generic run resume/recovery, the server scans the owner's
recent v2 records for the portfolio (the same bounded 40-row scan as the run
list) and, if a verified record for the same task carries a higher version,
refuses: start → `409 task_state_superseded` (nothing reserved), task resume →
outcome `superseded` (no run presented, nothing dispatched), generic resume /
recovery → the interrupted run is left as is. Migration 0020's transition RPC
also keeps both fields immutable. Limits: supersession is enforced against
*stored* runs, so it begins once the newer version is started (between confirm
and start an older version can still start); an owner who deletes their own
newer row (allowed after the insert window) removes the evidence.

Recovery: `POST /copilot/task-state/resume` requires the current JWT, re-verifies
the token and that its portfolio is the active one, then reads the run via the
caller-scoped journal (RLS, no service role, no persisted JWT) and compares the
current portfolio revision with the run's captured revision. Changed → marks the
version stale, returns `stale_account_changed`, dispatches nothing; a stale
version can only be replaced by an explicit re-confirm (version+1, new run id).
Same → `completed` / `run_failed` / `continuing` (interrupted/queued runs go
through the existing `JobJournal.resume` + dispatcher with its per-owner limit,
queue bound, lease and five-minute execution budget). Missing run →
`run_missing` with confirmed inputs kept.

Frontend: one typed form per open task, at the latest turn holding it, inside the
existing conversation and single input. Two panels: "You said · not confirmed"
(dashed) and "Confirmed parameters · version n" (accent), plus stale/superseded
notices and the clarification counter. Unconfirmed form edits are kept in session
storage per task; reload restores the thread, the task and the draft. Calculate
confirms server-side first, then starts exactly that version; "Resume task with
current login" calls resume. The e2e run found a real defect (a confirmed-version
prop update aborted the in-flight start); fixed and pinned by a unit regression.

### Limits

- Continuity covers the reduction-candidate task (goal/amount/protected). Put,
  financing-rule and APR clarifications remain single-turn prose.
- The token is client-held: losing session storage (new tab/device) loses the
  open task; durable runs remain listable via the existing recovery panel.
- Assumption parsing is lexical (EN/ZH patterns, uppercase tickers); lowercase
  tickers in chat are not recognised (ask → form).
- Changing `schemas/copilot_jobs.py` changes the job execution fingerprint, so
  queued pre-upgrade jobs fail with `execution_version_changed` after deploy (the
  existing, documented behaviour). The 2026-10-12 `task_id`/`task_version`
  fields changed that schema, so the fingerprint changed again; nothing is
  deployed with the async flag on, so no queued job is affected.
- Flags unchanged (decision support + async remain default off); no migration.

## 2026-10-10 — D: checkable research hypotheses (local, default-off)

Design, math and limits: [copilot-research-hypotheses.md](copilot-research-hypotheses.md).
`research_context[].hypotheses` (additive) turns user-stated views and method
questions into typed `ResearchHypothesis` records with sources, counterpoints,
invalidation conditions and a deterministic status; research evidence, model
inference and user assumptions are separate fields. A hypothesis can be carried
into the existing `compare-change` comparison only as a user-typed, explicitly
confirmed price change (`hypothesis` request field → `hypothesis_scenario`);
claim text is never sent. Method-card review dates are now gated by recorded
source re-verifications. No migration, new provider, retrieval or deployment.

## F follow-up: cross-device history and versioned metric review (2026-10)

See docs/plan-history-review-2026-10.md. Adds owner-scoped, cursor-paged history
over all three signed plan kinds, original-evidence reads verified on every
request, and a versioned review-metric contract that decomposes changes into
method / market / account parts (method change never totalled). In-session
periodic review is opt-in and bounded; offline monitoring is design-only. Both
flags (`MINDMARKET_PLAN_HISTORY_ENABLED`, `NEXT_PUBLIC_PLAN_HISTORY_ENABLED`)
default off. No migration. Put plans remain assumption-review only.
