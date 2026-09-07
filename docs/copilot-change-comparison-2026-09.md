# Copilot change comparison — local implementation, 2026-09-06

## Delivered scope

Within the existing single conversation, choose **Test a change** (or type that
exact task phrase), enter a held ticker and reduction in USD, and explicitly
choose account cash or margin repayment. No second chat window or page change.
Ordinary natural-language questions continue to use the existing single-turn
answer path; this is not a general trade-intent parser.

The paired result shows unchanged vs the user's assumption: net equity, cash,
loan, gross leverage, largest position/gross assets, annualized equity volatility,
historical 1-day 95% VaR and expected shortfall **for stock-only books**. Mixed
books instead show full-account instantaneous stresses and option-only expiry
bounds, with historical risk metrics explicitly unavailable. No health-score optimization,
recommendation, automatic alternative, trade, holdings mutation or saved plan.
Revise creates a new editable turn and leaves the previous result visible.
Each submission captures fresh data for BOTH sides, not an old baseline against
a fresh candidate.

## Architecture and numerical boundaries

- `schemas/copilot_compare.py`: strict typed request/result. Request accepts only
  portfolio identity, held ticker, positive finite cent-precision amount and
  proceeds destination, not client-calculated risk or replacement holdings.
- `api/v1/copilot_compare.py`: authenticated JWT-owned active context copied once,
  shared one-slot foreground risk semaphore, one history batch, and optimistic
  input-digest check before returning. No new queue, storage or LLM invocation.
- `services/copilot_compare.py`: pure validation and monetary transformation;
  existing `engine.quant.compute_portfolio_metrics` calculates BOTH stock-only sides from
  the same aligned returns object. No copied VaR/volatility formulas or changes
  to the canonical score engine.
- Decimal accounting preserves net equity before costs: selling to cash reduces
  securities and increases cash equally; selling to repay reduces securities
  and debt equally. Amounts exceeding the held value or loan are rejected, not
  silently resized. Fractional shares are an explicit model assumption.
- Dollar valuation uses the latest row of the captured adjusted-close matrix;
  this is a hypothetical closing-price reconstruction using captured account
  cash/debt, NOT a live quote/account statement or execution price.
- At least 60 common returns, 95% usable date coverage and a latest common close
  no more than seven calendar days old. Missing/invalid prices cannot be
  renormalized away. Returns are calculated before missing-row alignment.
  Intervals containing an extra weekday are conservatively omitted (including
  exchange holidays) so a missing date is not treated as a one-day move. There
  is no new exchange-calendar dependency or claim of exact session-calendar coverage.
- Existing cash yield / borrowing proxy remains 4.5% annually, not broker rates.
  Positive net equity and gross leverage ≤10× required; reject, do not clamp.
- Stock-only path assumes US-listed USD-priced long stocks/ETFs and account cash.
  Explicit non-USD currencies, exchange suffixes, unsupported asset metadata,
  disguised option metadata, short stock or invalid quantities
  block the WHOLE comparison before fetching data. Stocks with class suffix A/B
  are supported; other symbol types are conservatively unsupported. Missing
  currency metadata retains the platform's USD assumption, disclosed in the UI.
- No fund look-through, taxes, fees, execution, settlement, broker maintenance,
  or actual YTD claims. Lower margin does not guarantee no margin
  call; changes in modeled risk have changes in investment exposure as a tradeoff.
- Result fingerprint includes copied account inputs, assumptions, captured matrix,
  provenance and engine version. It is NOT a signature, replay artifact or save
  authorization. No high-privilege operation may trust a client-returned fingerprint.

Methodology context: [CFA Institute, Measuring and Managing Market Risk](https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/measuring-managing-market-risk)
distinguishes historical simulation from actual account returns and discusses
model limitations. [FINRA, Margin Calls](https://www.finra.org/investors/insights/margin-calls)
explains broker house requirements and liquidation risk. These sources do not
certify this implementation or its estimated risk values.

## Mixed-account extension (2026-09-06, local only)

Only the selected stock/ETF amount changes. All option legs remain unchanged;
there is no option order/roll/leg-edit workflow. `comparison_options.py` is a strict
capture/stress adapter around the existing `options_analytics`, `options_scenarios`
and `options_strategies` services. It does not copy option pricing/payoff formulas.
The shared analytics now accepts an optional capture clock; other callers retain
the existing default clock behavior.

- Strict identity: explicit valid underlying/type/expiry/strike, confirmed side,
  whole signed quantities, explicit multiplier 100, no adjusted deliverables.
  Stored OCC symbols, when present, must agree with metadata. Provider OCC symbol
  and strike must match exactly: the existing nearest-strike fetcher's neighboring
  row is rejected, never silently priced. Maximum 20 legs, no near-expiry ≤1 day.
- All stock and option-underlying prices come from one history batch. Each unique
  option is fetched once and frozen for both sides. Require finite two-sided
  bid/ask, positive bid, non-crossed quote and spread ≤50% of midpoint. Solve IV
  from that mark and the captured spot; reject impossible calibration/default-IV
  fallback, absent Greeks or missing legs. Entry premiums do not enter this
  forward-risk calculation. No network in the deterministic comparison service.
- Gross assets = stocks + cash + long option marks. Short option marks are
  liabilities separate from the margin loan. Equity = gross assets − short option
  liabilities − margin. Decimal conservation holds for cash and repayment routes.
  Gross assets/equity is mark-based leverage, **not** delta or notional exposure.
- Full-account scenarios: zero shock; equity −20% / IV +10 percentage points;
  equity +20% / IV −10 points. Known short-Treasury ETFs use ±1%, not zero risk;
  user-entered cash-equivalent claims do not confer this treatment. Shared model
  IV floor is 1%. All horizons are zero: full Black-Scholes reprice each leg at
  its own maturity, with no modeled settlement, interest accrual or cross-expiry
  path. Subtract the same model's zero-shock P&L to remove quote/model residual;
  zero-shock account P&L is zero on both sides. Model scenarios are not forecasts,
  probability estimates, or a worst-case loss guarantee.
- Grouped expiry bounds reuse the exact piecewise payoff engine, netted per
  underlying/expiry on the captured **mark basis**, not original trade cost.
  They exclude stock cover and cannot be summed into a cross-expiry account bound.
  A reduction in stock backing short calls gets a prominent warning. All options
  are repriced in account stress, not converted to a delta-only approximation.
- Delayed option quotes lack exchange timestamps; pairing them with stock closes
  is **not** a synchronized live brokerage valuation. Quotes may be stale. No
  actual broker equity reconciliation is claimed. The model omits American
  exercise/dividends; remaining time uses the shared rounded-day convention and
  expiry-date boundary, not exact exchange settlement time. Live-provider and
  real-account validation remain release gates.

Reference: [OIC bull call spread](https://www.optionseducation.org/strategies/all-strategies/bull-call-spread-debit-call-spread)
describes the expiry loss/gain bounds and assignment risk;
[OIC Black-Scholes](https://prd-web.optionseducation.org/advancedconcepts/black-scholes-formula)
explains the pricing model and its distinction from American exercise models.
Neither source validates this software. Regression fixtures derived from the
user's quoted spreads yield mark-basis loss/gain GOOGL $428/$1,572, ORCL
$442/$4,558 and NVDA $448/$1,552, without asserting those quotes are current.

## Frontend and recovery

`copilot-change.tsx` contains only form/presentation. `copilot-compare.ts` owns
runtime schemas/task phrase. The existing `use-copilot-thread` owns request and
session state. A `needs_input` turn persists partial assumptions under the existing
user/portfolio key; refresh never submits. Interrupted comparison inputs remain
editable; Stop waiting aborts the client and discards a late result but does not
preempt Python already running. No duplicate request while the local lane is busy.

The client verifies returned portfolio and exact assumptions before displaying.
Portfolio switches remount the scoped conversation; old responses cannot populate
the new book. Existing checks and signed-run retrieval stay separate and compatible.
Typing in an inline form does not trigger auto-scroll or focus stealing.

## Remaining work / release gates

Update: optional complete **comparison** receipts and exact same-version replay
are now implemented locally, default off; see [snapshot verification](copilot-comparison-replay-2026-09.md).
This does not enable run-journal storage or implement plan confirmation.

This is partial stage 2, not completion of the full Risk Agent plan. Mixed books
can compare stock reductions with unchanged standard option legs; option-leg
changes, general strategy candidates, synchronized quote/replay artifacts and
mixed-account historical VaR are not implemented here.
Also pending: inline correction of original holdings metadata, bounded semantic
multi-step coordination, durable/general risk-run priced artifacts, version-bound confirmed
plan save, cross-device history and later review workflows. Run journal 0014
remains off and unprovisioned; real PostgreSQL/RLS testing remains a separate gate.

No migration, production configuration, commit, push, PR or deployment was performed
in this turn. Local test/fixture success is not live-user or production validation.

## Previous stock-only local acceptance

- Complete backend: **1261 passed, 1 skipped**, measured coverage **88.78%** (85% gate).
- Comparison + scope targeted rerun after final type annotations: **52 passed**;
  comparison alone adds 43 cases (cash/debt conservation, exact amount constraints,
  same-frame math, full-sale cash, missing dates, invalid inputs, option/FX guards,
  auth/book changes and lane release).
- Complete frontend: **576 passed**, 116 files; TypeScript and lint passed.
- Production-like Next build + Playwright: **68 passed**, desktop and mobile
  fixtures, including input → reload → compare → revise and unsupported-book states.
- Black, Ruff, schema/core mypy (43 files), generated OpenAPI/TS contract and
  whitespace checks passed. Known test-environment JWT/deprecation warnings are
  not a live authentication/RLS proof; no provider or real-account smoke was run.

## Mixed extension local acceptance

- Backend full suite: **1287 passed, 1 skipped**, **89.02%** measured coverage
  against the 85% gate. Added 26 mixed-account cases. Focused final comparison
  rerun: **69 passed**; shared Black-Scholes/options plus comparison suite: **109 passed**.
- Frontend: **577 passed**, 116 files; TypeScript, lint and production-like build
  passed. Desktop/mobile Playwright: **70 passed**, including mixed-account result,
  unavailable-vs-zero distinction, grouped spread bounds, single composer and
  no horizontal overflow. Mobile result screenshot visually inspected.
- Black, Ruff, schema/core mypy (43 files), regenerated OpenAPI/TypeScript and
  whitespace gates passed. Existing test-environment JWT and library deprecation
  warnings remain; fixture auth tests are not live Supabase/RLS verification.
- Adversarial checks reject positive unsigned option counts, mismatched NVDA/NVDL
  identities, nearest strikes, missing/adjusted multipliers, wide/crossed/absent
  quotes and impossible IV. Duplicate lots reuse one contract quote; no-shock
  account P&L is exactly zero; entry premium cannot replace mark basis; covered
  stock reductions are flagged and cross-expiry groups remain separate.
- No production deployment, database migration, commit, push or real holdings
  change. The pre-existing export script executable-mode change is preserved.
