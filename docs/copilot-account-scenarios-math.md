# Whole-account funding scenarios — mathematical specification (v2)

Status: specification written **before** implementation (C/E follow-up to
`copilot-funding-scenarios.md`). Methodology id: `funding-account-scenarios-v2`.
Saved v1 records (`funding-common-expiry-v1`) keep their original meaning and
are never reinterpreted.

## 1. Objects and clock

* **Capture time `t0`** — `snapshot.captured_at` of the signed comparison
  receipt. Every alternative (including *no action*) starts from the SAME
  captured account `A0` (holdings, cash `C0`, debt `D0`) and the SAME market
  snapshot `M0` (last captured closing price `P0[u]` for every stock/underlying,
  every captured option row: contract identity, two-sided-quote midpoint `m_i`,
  implied volatility `σ_i` calibrated by the capture engine to `P0` and `t0`).
* **Market snapshot id** `sid = sha256(canonical JSON of {t0, A0, price-as-of
  date, P0, [(symbol, m_i, σ_i, spot_i)]})`. It is computed once; every
  alternative and every scenario outcome carries `sid`; a test asserts equality.
  Option-chain quote timestamps are not available from the provider; the quote
  time is reported as "captured with the comparison at `t0`", not as an exchange
  timestamp.
* **Valuation time `t_v = T`** — the expiry date of the new short Put (the
  scenario horizon). Date granularity (00:00 UTC of the calendar date).
* **Scenario** `s` — a user-supplied, explicit, probability-free vector of
  underlying prices `S_T[u] ≥ 0` at `T` for every held stock and every existing
  or new option underlying. No price is inferred. For an existing leg expiring
  at `e < T`, its settlement price `S_e[u]` must be supplied explicitly in
  `settlement_prices[e][u]`; otherwise that leg (and every figure that depends
  on it) is **not computable**.

## 2. Inputs

| Input | Source label | Missing ⇒ |
| --- | --- | --- |
| `P0[u]` | captured close (signed receipt) | request refused (capture already strict) |
| `m_i` option mark | captured two-sided-quote midpoint | capture refused |
| `σ_i` residual IV | `captured_quote_implied_vol` (capture calibration) **or** `user_assumption` (explicit per-contract override, requires `residual_assumptions_confirmed=true`) | residual leg not computable |
| `r` residual rate | `user_assumption` (`residual_risk_free_rate`, continuous) — never defaulted | residual leg not computable |
| APR `a` | `user_assumption` (`annual_borrowing_rate`, simple Actual/365) | interest unknown ⇒ debt-dependent figures `None` |
| sale amount/fee, Put terms, reserves | signed funding assumptions | refused |
| broker rules | `broker_rules` provider (`unknown` is the only built-in) | buying power / maintenance / naked-call collateral **unknown** |
| ranking objective | user-confirmed `objective` + `objective_confirmed` | no ranking |

## 3. Per-leg treatment at `T`

Signed contracts `q` (long > 0, short < 0), multiplier `μ = 100`, strike `K`,
expiry `e`. Physical settlement; **no early exercise is modelled**; ATM (`S = K`)
and OTM legs expire without exercise; ITM long legs are exercised (automatic
exercise assumption).

1. `e ≤ T` (settles; price `S = S_T[u]` if `e = T`, else `S_e[u]`):
   * put ITM (`S < K`): a short put (`q<0`)
     receives `|q|μ` shares and pays `K|q|μ`; a long put (`q>0`) delivers
     `qμ` shares and receives `Kqμ`.
   * call ITM (`S > K`): a short call delivers `|q|μ` shares and receives
     `K|q|μ`; a long call receives `qμ` shares and pays `Kqμ`.
   * Delivering more shares than held produces a **short stock** position,
     valued at `S_T` and flagged (`short_stock_after_settlement`).
   * Cash events are applied in expiry order; `min_cash_through_T` is the lowest
     running cash after each settlement date (no interest on it).
2. `e > T` (residual, still open at `T`): value per share
   `V = BS(S_T, K, τ, r, σ)`, `τ = (e − T)_{days} / 365.25` (the capture engine's
   year basis). `S_T = 0` uses the analytic limit: call `0`, put `K·e^{−rτ}`.
   Position value `qμV` (a short leg is a liability). **Never** the expiry
   payoff, never zero. Missing `σ` or `r` ⇒ the leg's value is `None` and every
   outcome figure that sums it is `None` with reason codes.

The new Put (candidate alternatives only) expires at `T` and is case 1.

## 4. Ledger per alternative `k` and scenario `s`

Start state after the alternative's instantaneous funding action at `t0`:

* *No action*: shares `Q0`, cash `C0`, debt `D0`.
* *Sell & keep cash*: `Q0[x] −= n_x` with `n_x = amount / P0[x]`;
  cash `C0 + N`, `N = amount − sale_fee`; debt `D0`.
* *Sell & repay*: as above with repayment `R = min(N, D0)`: cash `C0 + N − R`,
  debt `D0 − R`.
* Candidates add the new Put: cash `+= premium·μ·c − put_fees`, and a new short
  Put leg.

Initial equity (same for every alternative, from `M0`):
`E0 = Σ_u Q0[u]P0[u] + C0 + Σ_i q_i μ m_i − D0`.

At `T`: `cash_T` after all settlements; positions `Q_T`; stock value
`Σ Q_T[u] S_T[u]` (long and short separately); residual option value
`O_T = Σ_{e>T} q μ V`.

* interest `I = 0` if debt `= 0`, else `D·a·days(t0→T)/365` if `a` given, else `None`.
* `E_T = Σ_u Q_T[u]S_T[u] + O_T + cash_T − D − I`.
* `PnL = E_T − E0`; `ΔPnL_k = PnL_k − PnL_{no action}`.
* **Opportunity cost of sold stock** `OC = n_x·(S_T[x] − P0[x])` (gain forgone;
  negative when the price fell). It is a *decomposition line* only — it is
  already inside `E_T` because the sold shares are absent; it is never
  subtracted again. Invariant (no residual legs, no interest):
  `ΔPnL_keep = −OC − sale_fee + newPutPayoff`, `newPutPayoff = premium·μc −
  fees − μc·max(K−S_T,0)`.
* **Fees** are counted once: sale fee inside `N`, put fees inside cash.
* Reserves `ρ = other_reserved + buffer + Σ_{open short puts at T} K|q|μ`
  (gross, no spread netting). An open **uncovered** short call at `T` has a
  collateral requirement only a broker rule can supply ⇒ `funding_gap = None`.
  `gap = max(0, ρ − (cash_T − I))`.
* Leverage `L = gross_long / E_T`, gross_long = long stock + long option value +
  cash after interest + financed gap; `None` when `E_T` is unknown or `≤ 0`.
  Largest-position weight uses long stock value only; `None` when `E_T ≤ 0`.

### Conservation invariants (tested)

1. *Assignment conservation*: for every settlement, `Δcash = −K·Δshares` for
   every exercise/assignment event; net-equity change of settlement at `S` equals
   the option's intrinsic payoff `q μ (S−K)^+` (call) / `q μ (K−S)^+` (put).
2. *Funding conservation*: keep-cash and repay alternatives have identical
   `cash − debt` at `t0` and identical `E_T` before interest.
3. *Shared snapshot*: every outcome's `snapshot_id = sid`.
4. *No premium as profit*: at `t0` each candidate's equity changes only by
   `−sale_fee − put_fees`.

## 5. Coverage / protection relationships

Computed per alternative at `t0` (after the funding action) and per scenario at
`T` for legs still open, by a deterministic pairing per underlying:

1. Short calls (sorted by expiry, strike) are covered first by shares
   (`⌊shares/100⌋` contracts), then by long calls with expiry `≥` the short's
   (lowest strike first). Remaining contracts are **uncovered**: max loss
   unbounded (`None`), collateral = broker-rule unknown.
2. Short puts are paired with long puts expiring no earlier (highest strike
   first): max loss excluding premium `max(0, K_s − K_l)·μ·n`; otherwise
   cash-secured: `K·μ·n`.
3. Remaining long puts protect remaining long shares (`protective`); a long
   put without shares is `unpaired_no_stock` (exercise would create a short).

A relationship that differs from the no-action alternative (e.g. covered call
→ uncovered because the sale removed the shares) is listed in
`coverage_changes` with the reason, and the alternative's nested funding status
becomes `financing_rules_required`.

## 6. Broker rules

`broker_rules.py` exposes a versioned provider interface `(provider_id,
rule_version, source)`. The only built-in provider is `unknown`; every
requirement (buying power impact, maintenance margin, naked-call collateral)
returns `status = "unknown"` with a reason. No Reg-T or house rule is encoded.

## 7. Conditional ranking

Only when (a) the user confirmed an objective and (b) **every** alternative has
every compared metric computable in every scenario and no alternative carries an
unbounded max loss. Objectives map to loss-direction vectors (lower is better):

* `preserve_terminal_equity`: `[−E_T(s)]_s`
* `minimize_funding_gap`: `[gap(s)]_s`
* `minimize_conditional_debt`: `[D + gap(s)]_s`

An alternative is *preferred* only if it is no worse in every entry and strictly
better in at least one versus **each** other alternative (the dominance rule of
`copilot_candidates.py`). Otherwise `no_dominant_alternative`. Never ranked by
LLM opinion.

## 8. Not computable (stated, never defaulted)

* settlement price for an earlier-expiring leg not supplied;
* residual IV or rate not supplied/confirmed;
* interest with unknown APR on a debt-bearing branch;
* funding gap with an open uncovered short call (broker collateral);
* buying power, maintenance requirements, margin calls, liquidation paths,
  actual fills, early exercise, dividends, taxes, settlement timing.
