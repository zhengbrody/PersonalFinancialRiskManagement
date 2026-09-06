# Copilot change comparison — local implementation, 2026-09-06

## Delivered scope

Within the existing single conversation, choose **Test a change** (or type that
exact task phrase), enter a held ticker and reduction in USD, and explicitly
choose account cash or margin repayment. No second chat window or page change.
Ordinary natural-language questions continue to use the existing single-turn
answer path; this is not a general trade-intent parser.

The paired result shows unchanged vs the user's assumption: net equity, cash,
loan, gross leverage, largest position/gross assets, annualized equity volatility,
historical 1-day 95% VaR and expected shortfall. No health-score optimization,
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
  existing `engine.quant.compute_portfolio_metrics` calculates BOTH sides from
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
- First version assumes US-listed USD-priced long stocks/ETFs and account cash.
  Explicit non-USD currencies, exchange suffixes, unsupported asset metadata,
  options (including disguised option metadata), short or invalid quantities
  block the WHOLE comparison before fetching data. Stocks with class suffix A/B
  are supported; other symbol types are conservatively unsupported. Missing
  currency metadata retains the platform's USD assumption, disclosed in the UI.
- No fund look-through, taxes, fees, execution, settlement, broker maintenance,
  actual YTD or option scenario claims. Lower margin does not guarantee no margin
  call; changes in modeled risk have changes in investment exposure as a tradeoff.
- Result fingerprint includes copied account inputs, assumptions, captured matrix,
  provenance and engine version. It is NOT a signature, replay artifact or save
  authorization. No high-privilege operation may trust a client-returned fingerprint.

Methodology context: [CFA Institute, Measuring and Managing Market Risk](https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/measuring-managing-market-risk)
distinguishes historical simulation from actual account returns and discusses
model limitations. [FINRA, Margin Calls](https://www.finra.org/investors/insights/margin-calls)
explains broker house requirements and liquidation risk. These sources do not
certify this implementation or its estimated risk values.

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

This is partial stage 2, not completion of the full Risk Agent plan. Options-aware
same-snapshot account comparison is still required for the owner's mixed book.
Also pending: inline correction of original holdings metadata, bounded semantic
multi-step coordination, full priced artifact replay, version-bound confirmed
plan save, cross-device history and later review workflows. Run journal 0014
remains off and unprovisioned; real PostgreSQL/RLS testing remains a separate gate.

No migration, production configuration, commit, push, PR or deployment was performed
in this turn. Local test/fixture success is not live-user or production validation.

## Local acceptance

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
