# Captured reduction and Put funding scenarios

This read-only composition is independently gated by `MINDMARKET_FUNDING_SCENARIOS_ENABLED` (default off), plus decision support, cash-secured Put and comparison replay gates. It requires an authenticated comparison receipt belonging to the caller and selected portfolio. A revision-less, stale, future-dated, altered or different-implementation receipt is rejected. Inputs and revision are checked again before returning.

`POST /api/v1/copilot/funding-scenarios` returns exactly three alternatives:

1. No action: no sale, no new Put, original cash and debt.
2. Sell the captured amount, retain net proceeds as hypothetical settled cash, evaluate the new Put's gross cash obligations.
3. Sell the same amount, repay the lesser of debt and net proceeds, retain any excess, evaluate the same Put.

The sale uses the original closing price and a user-supplied sale fee. The original immutable snapshot is replayed, then copied. No account, position, plan or order is written. A user-protected holding or the underlying of any existing option cannot be sold through this model. Existing option holdings are subsequently subject to the standard Put engine's strict contract and obligation validation; complex legs are rejected.

For net proceeds N, starting cash C and debt D:

- Retain cash: cash = C + N, debt = D.
- Repay debt: repayment = min(N, D), cash = C + N - repayment, debt = D - repayment.
- Cash minus debt is identical for the two alternatives. Initial net-equity change is sale fees plus Put fees, never premium income.

The standard Put engine is reused for gross cash collateral and terminal payoff arithmetic with a copied zero-debt calculation context. The outer alternative **always retains the actual hypothetical debt**. Any remaining debt forces `financing_rules_required`, regardless of the nested gross-collateral status. Consumers must not present the nested `put.funding_status` as financing eligibility.

`assignment_cash_shortfall` is the maximum terminal funding gap after premium, cash reservations and buffer in the returned Put scenarios. `hypothetical_debt_if_shortfall_financed` adds that gap to remaining debt; it is a conditional accounting amount, not credit availability. Pre-trade collateral still excludes new premium. Neither result supplies broker buying power, maintenance margin, a preferred alternative, or permission to trade.

The nested Put payoff is incremental for the new Put only. It excludes sold-stock opportunity cost and existing portfolio P&L. Consequently this is a funding comparison, not a total-portfolio risk/return ranking. The original captured reduction still contains its existing risk analysis. The computation engine issues no receipt itself. A separately gated combined-plan service can authenticate the combined result using its own signing purpose and confirmation type; it must never silently save it as a standalone cash-secured Put plan.

## Verification

Twelve focused tests exercise real deterministic comparison replay, cash/debt conservation, fee loss, pre-trade and assignment deficits, no mutation, protected holdings, consent, stale/future captures, replay mismatch, ownership and revision fences, and the disabled feature gate. The suite plus existing Put and replay tests passes 61 tests. Four injected regressions (age limit, protected holdings, debt repayment and replay bypass) fail the focused suite; original bytes were restored and the suite rerun successfully.

Broker-specific financed/complex strategies, actual execution/settlement verification, total-portfolio combined risk calculation, remain distinct unsupported capabilities. No production feature has been enabled by this change.

Public assumptions echo all inputs except the opaque receipt; captured_at identifies the original market/account snapshot, while computed_at identifies composition time. Pre-Put concentration and absolute dollar VaR are taken directly from the replayed reduction. Mixed-account VaR remains null. These metrics exclude the new Put, and instantaneous stresses must not be added to expiry P&L across different horizons. Each expiry funding row leaves interest_cost null because borrowing APR and actual borrowing dates are unknown. Same-underlying old and new short Puts reserve full strike cash without netting.

## Original C/E scope audit — 2026-09-17

The current implementation completes a bounded **funding composition**. It does
not complete the original C/E objective of comparing total account risk and
return after reductions, financing changes and option assignment. The following
engineering gaps exist even with all external providers disconnected; they must
not be relabelled as deployment validation or missing API credentials.

| Original requirement | Implemented behavior | Exact remaining scope |
| --- | --- | --- |
| Same snapshot, no action and at most two candidates | Signed reduction capture; unchanged baseline and two sale-funding allocations | The two combined allocations lack comparable total-account scenario outcomes and therefore have no conditional preferred choice |
| Compare cash, debt and concentration | Net sale proceeds, capped debt repayment, existing cash reservations and pre-Put concentration/VaR | Concentration, leverage and portfolio risk **after the new Put or assignment** are not computed |
| Compare downside and losses of protection | New Put expiry payoff and conservative refusal to sell an existing option underlying | Existing positions' scenario P&L, sold-stock opportunity cost and changes to protection are not valued together |
| Explain assignment funding | New Put strike obligation, cash deficits and debt if a deficit could be financed | Interest accrual, timing of a financing draw, early assignment branches, and simultaneous exercise/assignment cash movements are not modeled |
| Existing option relationships | Existing short Puts retain full gross collateral, including same-underlying contracts; other option legs are rejected | Long Puts, calls, verticals, covered calls, mixed expiries and protection adjustments need an explicit combined delivery and collateral model |
| Conditional preference | Original stock-reduction comparison may have a conditional judgment; combined funding results have no preferred alternative | An objective-specific comparison over complete, same-horizon combined outcomes is still required; unknown risk must continue to prevent ranking |
| Financing and broker buying power | Remaining debt is never erased; financing feasibility and buying power remain unknown | There is no versioned broker-rule evaluator, financing eligibility calculation or maintenance-margin/buying-power simulator |

### Pure engineering not yet implemented

1. **A shared scenario clock and full-account ledger.** All baseline and candidate
   positions must be valued at the same scenario time. The ledger must include
   retained stock/ETF values, cash, debt, sale fees, new option liabilities,
   existing option value, delivered shares and strike cash. The current new-Put
   expiry P&L cannot simply be added to an instantaneous stress result. A common
   horizon is an implementation requirement, not a data-provider dependency.
2. **Post-Put and post-assignment portfolio metrics.** Recompute concentration
   with an explicitly named denominator, gross/net equity and leverage after
   each delivery branch. Preserve unknown volatility/VaR when the selected
   engine cannot value the mixed account. Current `pre_put_*` values cannot
   substitute for those metrics.
3. **Exercise, delivery and protection relationships.** Introduce explicit leg
   dependencies and assignment/exercise cash flows. Model removing or changing a
   protection leg before enabling such an edit. Reject unsupported mixed-expiry
   paths as a whole rather than dropping legs or assuming hedge offsets.
4. **A financing cash-flow interface.** Accept a named, dated rule set plus
   explicitly confirmed rate and borrowing-time assumptions. Interest requires
   rate, principal path, accrual basis and borrowing duration; an unknown value
   must stay unknown, not become zero. The current `interest_cost: null` is
   correct disclosure of an unimplemented calculation. A hypothetical financing
   engine can be built and tested with disclosed synthetic/user assumptions
   before broker connectivity exists.
5. **Comparable judgment and explanations.** Once full-account outcomes exist,
   compare no action and both alternatives against a declared objective such as
   preserving a minimum cash buffer or reducing peak debt. Require complete
   coverage before selecting an alternative, and return concrete missing inputs
   otherwise. New-Put maximum loss alone is not a sufficient ranking metric.
6. **Contracts and regression coverage for that extended methodology.** Add
   typed scenario inputs and signed outputs, replay fingerprints, conservation
   invariants and frontend labels for the new horizon and metric definitions.
   Extend the separate combined-plan confirmation/review flow without changing
   the meaning of already saved version-one evidence.

### External evidence needed for real-account claims

- Authorized broker data for settled versus unsettled cash, buying power, margin
  debit, open-order reservations, exercise restrictions and account permissions.
- Broker-specific, effective-dated house margin/collateral rules, portfolio-margin
  treatment and financing rates. A tested generic rule interface does not prove
  that its rules describe a particular live account.
- Authorized and sufficiently fresh option quotes, contract deliverables,
  adjusted-contract flags, underlying prices and any valuation inputs needed at
  a pre-expiry horizon. Manual inputs can support labelled hypothetical analysis,
  but cannot establish executable prices or actual contract eligibility.
- Actual execution/settlement and assignment records if the product later claims
  that a hypothetical sale or option assignment happened. Saved assumptions are
  not execution records.

These dependencies limit **verification of live claims**. They do not block
writing the deterministic ledger, rule interface, explicit missing-data handling
or synthetic regression tests described above.

### Executable next engineering stage

Build a version-two total-account expiry comparison for long USD stocks/ETFs,
account cash/debt and standard physically settled short Puts sharing the chosen
expiry. Keep different-expiry options and other option types explicitly
unsupported for this first stage. Require an explicit scenario price for every
held underlying at the shared expiry; do not infer missing prices as unchanged.

For each scenario, evaluate no action and both funding alternatives from the
same original account. Preserve existing Put assignment obligations in every
alternative, add the new Put only in the candidate rows, debit all strike cash,
credit delivered shares and retain debt separately. Provide a paired table of
net equity, total-account P&L relative to the captured account, liquidity deficit,
post-assignment concentration and debt. Add an optional hypothetical interest
schedule with explicit inputs; leave financing feasibility unknown without an
applicable verified rule set. Only then implement objective-specific conditional
preference for fully covered scenarios.

Acceptance must include conservation of cash/assets/liabilities, the same
existing assignments across baseline and candidates, sold-stock opportunity
cost, no-premium-as-instant-profit, fees, insufficient funding, incomplete price
vectors, protected holdings, signature/revision failures and replay after
implementation changes. Follow this with an explicit residual-option valuation
and protection-dependency stage before expanding to mixed expiries, long
protection legs and broker-specific portfolio margin.

This audit therefore does **not** declare the original C/E roadmap or all
predeployment engineering complete. The current release candidate can be
assessed as a narrower signed funding-analysis capability while those engineering
items remain openly tracked.


## 2026-09-19 common-expiry ledger implementation

The optional `risk` request now accepts one to three complete, explicit terminal
price vectors and an optional hypothetical annual borrowing rate. The
`account_risk` response compares the unchanged account and both funding choices
at the same expiry, including existing short Put assignment, delivered shares,
entry option liabilities, sold-stock opportunity cost and fees. APR uses simple
Actual/365 interest on each alternative's beginning debt. Missing APR remains
unknown for indebted alternatives; terminal funding deficits are not charged
retroactive interest. Nonpositive or unknown equity does not produce leverage
or concentration ratios.

These inputs and outputs are covered by combined-plan signatures and full
calculation replay. The implementation fingerprint includes the ledger and its
schema. The editor remains within the existing Copilot candidate flow. This
implements the common-expiry engineering stage above; it does not implement
mixed-expiry residual option valuation, early exercise paths, long protection
legs, broker-specific margin rules or automatic candidate ranking. Standalone
Put rows retain their separate, narrower payoff meaning.

Keep Python/FastAPI and TypeScript/Next.js. No C++ or Java service is introduced:
a new runtime is not needed for this bounded deterministic ledger. Any future
native optimization should follow profiling with representative workloads.

## 2026-10-11 v2 whole-account scenarios

`funding-account-scenarios-v2` replaces the common-expiry restriction; the
specification is `copilot-account-scenarios-math.md`. One captured snapshot id
binds every alternative; mixed expiries are supported (earlier legs need explicit
settlement prices, later legs are valued by Black-Scholes at the valuation date
with captured or confirmed IV and an explicit rate, otherwise not computable);
calls, long Puts and spreads are settled and coverage-checked; a sale that
uncovers a short call is flagged and blocks ranking. Broker rules come only from
the `unknown` provider. Ranking requires a confirmed objective and complete,
bounded metrics. Saved v1 records keep their v1 meaning.
