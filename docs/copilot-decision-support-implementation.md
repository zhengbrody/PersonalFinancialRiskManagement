# Copilot decision support — first implementation slice

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

This slice uses a **fixed two-minute execution lease**, not renewable multi-step
leases. It is a bounded single calculation, not the full resumable coordinator.
After interruption the user explicitly resumes with a freshly verified login;
there are at most two attempts, and recomputation captures fresh market data.
GET never starts computation. No JWT is persisted. An expired JWT or a restart
cannot trigger privileged recovery: the user must resume. There is no global
credential-bearing sweeper and no claim of unattended crash recovery.

Results remain readable for one day, independent of execution time. This is an
application visibility TTL: physical database cleanup is not yet implemented.
There is no cross-device run listing. These omissions, deployment-grade worker
lifecycle, automatic dispatch recovery, lease renewal, cleanup ownership and
P50/P95 measurement remain B follow-up work; **do not mark all of B complete**.

The state exposes queued/capturing/done. It does not fabricate detailed tool
progress or reveal model reasoning. Worker credentials are transient and the
stored results carry no JWT, service-role key or model configuration.

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

Production activation has **not** been performed. It needs reviewed 0014/0016
application, an independent run signing key, authenticated end-to-end acceptance,
worker/deployment lifecycle acceptance, representative latency checks and the
professional review identified in the design for public personalised suggestions.
Local SQL tests do not substitute for that evidence.

Still outside this slice: free-form multi-turn task state, renewable steps,
Research retrieval/claim linking, new hypothetical option legs, assignment and
broker buying-power calculations, option strategy modification, cross-time
versioned review and scheduled monitoring. E and the new parts of F are not
implemented. Existing user-confirmed comparison/save functionality is reused.

The first sell-Put question now leads to a scoped funding comparison. It does
**not yet** answer whether a new put is affordable or suitable after assignment.
Do not present this slice as the complete sell-Put decision loop.
