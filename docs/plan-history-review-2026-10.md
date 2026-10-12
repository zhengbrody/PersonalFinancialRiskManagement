# Saved-plan history and versioned review metrics (F, 2026-10)

Status: implemented locally behind `MINDMARKET_PLAN_HISTORY_ENABLED` (backend)
and `NEXT_PUBLIC_PLAN_HISTORY_ENABLED` (frontend build). Both default **off**.
Offline continuous monitoring is **design only** (section 6) and is absent from
the code. No migration: the existing `comparison_confirmations` table (0015,
written by 0015/0018/0019 RPCs) is the only storage read.

This document was written before the implementation; it is the contract the
code and tests are checked against.

## 1. Scope

| Plan kind | Stored by | Signed evidence domain | History | Metric review |
| --- | --- | --- | --- | --- |
| Reduction comparison | `confirm_copilot_comparison` (0015) | `comparison_save._key()` | yes | yes (stock/ETF books) |
| Cash-secured Put | `confirm_copilot_put_plan` (0018) | `put-plan:confirmation` | yes | **not computable** (no captured price history; see 3.6) |
| Funding scenario | `confirm_copilot_funding_plan` (0019) | `funding-plan:confirmation` | yes | yes, anchored on its signed source comparison |

A history row is only returned after its HMAC verifies under one enabled
domain AND every binding (user, portfolio, plan id, confirmation window)
matches. The kind is decided by *which key verifies*, never by a label in the
stored JSON. Rows that verify under no enabled domain are counted, never shown.

## 2. History reads (cross-device)

* `GET /api/v1/copilot/saved-plans?expected_portfolio_id=…&cursor=…` — at most
  20 verified items per page; a page inspects at most 21 rows.
* `GET /api/v1/copilot/saved-plans/{plan_id}?expected_portfolio_id=…` — the
  full original result plus an evidence fingerprint.
* Inputs are the caller's JWT and the portfolio id only. Nothing comes from
  `sessionStorage`, the originating tab or a client-held receipt, so a fresh
  browser on another device reads the same plans.
* Scope: PostgREST runs as the caller (RLS `user_id = auth.uid()`), the query
  filters `portfolio_id`, and verification re-checks the signed user/portfolio.
  A plan saved for portfolio P is never returned under portfolio Q, even when
  the owner later moves the editable `risk_plans.portfolio_id` to Q.
* Order: keyset on `plan_id` (UUID order). This is a stable, delete-safe order,
  **not** chronological; the UI says so. A plan saved after the first page was
  read can appear on a later page or require a reload.
* Cursor: `<last plan id>.<HMAC(user:portfolio:id)>` under a separate
  `plan-history` purpose — a cursor minted for portfolio P is rejected for Q.
* Immutability: editable fields live in `risk_plans` (title, status, notes,
  even `portfolio_id`). Evidence lives in `comparison_confirmations`, which has
  no UPDATE/DELETE grant for `authenticated`. Reads never consult `risk_plans`,
  so an edit cannot change the evidence bytes, the signature, or the verified
  result. `evidence_sha256` = SHA-256 of the exact signed record bytes, shown
  so a user can see two reads returned the same evidence.

## 3. Versioned review-metric contract

### 3.1 Notation

* `A0` — account captured in the signed snapshot (holdings, cash, margin).
* `P0` — the signed price matrix captured with it (adjusted daily closes).
* `A1` — the account read now, from the same portfolio, by the caller's JWT.
* `P1` — price history fetched now for the union of `A0` and `A1` symbols,
  same request shape as the original (`days=365`).
* `v0` — method of the original: its `methodology_version` + the signed
  implementation fingerprint. `v1` — the fingerprint of the running code.
* `M_v(A, P)` — metric evaluated by method `v` on account `A` and prices `P`.
  `M0 = M_v0(A0, P0)` is the **signed** baseline ("keep as is" side) value.

### 3.2 Metrics (contract version `plan-review-metrics-v1`)

| metric_id | unit | horizon | definition (same as the original baseline side) |
| --- | --- | --- | --- |
| `net_equity` | usd | point in time | Σ shares·last close + cash − margin |
| `leverage` | ratio | point in time | (Σ shares·last close + cash) / net equity |
| `largest_position_weight` | fraction | point in time | max position value / Σ position values (cash excluded) |
| `annual_volatility` | fraction per year | annualised from daily returns | `engine.quant.compute_portfolio_metrics` |
| `var_1d_95_usd` | usd | 1 trading day, 95% | daily VaR fraction × net equity |
| `cvar_1d_95_usd` | usd | 1 trading day, 95% | daily expected shortfall fraction × net equity |

Data window, reported per evaluation: `price_as_of` (last common close),
`history_start` (first return used), `observations` (return count). The same
data rules as the original apply: ≥60 common daily returns, ≥95% date
coverage, last close ≤7 days old at the valuation time, gaps never turned into
one-day returns. Cash and borrow both use the existing 4.5% model proxy.

Valuation times: `M0` and `M_v1(A0,P0)` at the original `captured_at`;
`M_v1(A0,P1)` and `M_v1(A1,P1)` at the review time.

### 3.3 Decomposition

Sequential, with an exact additive identity:

```
method_change  = M_v1(A0,P0) − M_v0(A0,P0)      # same inputs, different code
market_change  = M_v1(A0,P1) − M_v1(A0,P0)      # same holdings, new prices
account_change = M_v1(A1,P1) − M_v1(A0,P1)      # holdings/cash/debt changed
total_change   = M_v1(A1,P1) − M_v0(A0,P0)
               = method_change + market_change + account_change
```

Order matters: prices move first with `A0` held fixed; any interaction
between new prices and new holdings is attributed to `account_change`. This is
a definition, not a causal claim; the UI labels it as such.

### 3.4 Method comparability (never an "improvement")

* **Same method**: `v1 == v0` AND the current evaluator reproduces the signed
  `M0` on `(A0,P0)` (the replay tolerance of `comparison_replay`: exact except
  for the documented last-bit fields). Then `method_change = 0`,
  `market_change = M_v1(A0,P1) − M0` and the identity holds exactly.
  `status = comparable`.
* **Same fingerprint but not reproduced**: an evaluator bug. Every component
  is withheld; `status = not_computable`, reason `method_not_reproduced`.
* **Different method** (`v1 != v0`): the original cannot be re-run under old
  code. It is recomputed both ways on the *same signed inputs*: `M0` (old) vs
  `M_v1(A0,P0)` (new). `method_change` is reported separately and labelled
  "calculation method changed — not a change in your account". `total_change`
  is **withheld** (`status = method_changed`), so a method change can never be
  read as the account getting better or worse. Market and account components
  are reported under the current method only.

### 3.5 Missing data

Each of the four evaluations either succeeds or yields a reason code
(`price_history_missing`, `price_history_stale`, `unsupported_holdings`,
`account_has_options`, `unsupported_leverage`, `account_unavailable`). A
component that needs a missing evaluation is `null` with that reason. No
component is defaulted to zero, carried forward or partially summed.

### 3.6 What is not computable, stated

* Put plans: the signed snapshot holds the account but no price history and
  no account-level baseline metric, so there is no `M0`; review stays the
  existing assumption review.
* Mixed option books (`risk_method = mixed_instant_stress`): the original has
  no historical volatility/VaR, and re-marking options needs a live chain.
  Every metric is `not_computable` (`account_has_options`).
* Realised returns: there are no execution records, so the review never
  attributes actual outcomes. `realised_return_attribution` is always `false`.

## 4. Review modes

### 4.1 Manual review

`POST /api/v1/copilot/saved-plans/{plan_id}/metric-review`. Read-only: no
writes to holdings, plans or evidence. Runs inside the existing single
analysis lane (non-blocking; busy → 429) because it fetches prices. The
portfolio revision and scope digest are checked before and after, as in the
existing Put/funding reviews.

### 4.2 In-session periodic review (implemented, opt-in)

* Off until the user ticks the box in the Saved plans card; consent is held in
  memory, bound to the token and portfolio, and cleared on either change.
* Runs only while the signed-in Copilot window is mounted and visible.
* Bounded: first 5 loaded plans, one at a time, every 15 minutes; it stops on
  the first error and requires re-consent.
* Notifies only when the rounded decomposition changes from the previous tick
  (no repeated alerts for an unchanged state).
* Nothing is persisted; there is no service worker, no stored JWT, no server
  job.

## 5. UI

Single Copilot window, collapsed "Saved plans" card: paged history list,
"Open original evidence" (original figures, capture/confirmation time,
method, evidence fingerprint), "Run review" (decomposition table with labelled
components and window), and the opt-in periodic checkbox. Copy states that no
trades were executed and no returns are attributed.

## 6. Offline continuous monitoring — DESIGN ONLY (not implemented, OFF)

Nothing below exists in code. Building it needs a separate owner decision.

* **Authorization**: a separate, explicit opt-in per plan, revocable, stored as
  a row the user can read and delete. The user's JWT is never stored. The
  worker would hold a narrowly-scoped server credential and act only on rows
  carrying a live consent.
* **Least privilege**: the worker reads only consented portfolio ids and their
  evidence rows, writes only its own review results table; it cannot write
  holdings, plans or evidence, and cannot read other columns. Market data via
  the existing provider layer only. No LLM.
* **Scheduling**: bounded (e.g. once per trading day after close), global and
  per-user caps, jitter, and a stable episode id per (plan, change fingerprint)
  so an unchanged state never notifies twice.
* **Deletion**: deleting the plan, the portfolio, the consent or the account
  cascades the consent and every stored review; a retention cap removes old
  results. Notifications carry no tickers, amounts or emails in analytics.
* **Honesty**: same contract as section 3; still no realised-return claims.
