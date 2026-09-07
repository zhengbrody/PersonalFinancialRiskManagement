# Copilot risk check — Phase 1A implementation and acceptance

Date: 2026-09-05 Pacific. Branch: `codex/copilot-risk-check`.
Status: local implementation; **not deployed, not a complete autonomous Agent**.
Parent scope: [Risk Agent product plan](risk-agent-product-plan.md).

Continuation on 2026-09-06: an optional signed foreground-run journal now exists;
see [Phase 1B foundation and activation checklist](copilot-runs-2026-09.md). The
1A transport described below remains the default when that feature is off. No
database migration has been applied. Later combined-suite counts are in that note.

## Delivered experience

One Copilot input and timeline replace the separate Ask and Chat boxes. Page and floating views use the same user/portfolio-partitioned session history. Ordinary questions use the existing grounded six-section `/copilot/ask` contract; only the direct answer and portfolio relevance open initially. Evidence, assumptions and limits expand in place. Legacy chat API endpoints remain unchanged; the new UI no longer uses their SSE transport.

The explicit **Check my portfolio** action runs the existing authenticated report once. A pure server-side projection presents at most three findings, optional strategy expiry bounds, and expandable metrics with unit, horizon, calculation basis and source field. It does not send the full report to an LLM or create a second financial engine. Other wording uses the existing question router; this is not a model-driven tool planner yet.

The flow has visible waiting, failed, cancelled and interrupted states, retry and rerun controls. Query-string prefills never auto-submit. Typing/reading focus is preserved, IME Enter is handled, and the mobile composer clears the bottom navigation. Existing insights and Risk Fit preferences remain outside the conversation; full conversion into task messages is not claimed.

## Financial meanings and source map

These are established portfolio-risk concepts made readable, not a claim of institutional certification or full hedge-fund risk coverage.

| Display | Existing authoritative value | Interpretation and limits |
| --- | --- | --- |
| Bad-day loss threshold | `losses.var_1d_95.usd` | Historical 95% **one-day** VaR; never the 21-day Monte Carlo headline; not maximum loss |
| Worse-tail average loss | `losses.cvar_1d_95.usd` | Historical expected shortfall, not a guaranteed loss cap |
| Return dispersion | `annual_volatility` | Annualized model volatility, not actual YTD return |
| Largest single-name exposure | `concentration.top_holding_weight` | Invested exposure; cash excluded; options may enter as delta equivalents |
| Market sensitivity | `factor_betas[SPY].beta` | Portfolio-factor regression for the modeled basket, before account-level leverage scaling. **Not** `betas.SPY`, which is the SPY holding's individual beta |
| Diversification ratio | `correlation.diversification_ratio` | Historical weighted asset volatility / portfolio volatility; correlations can change under stress |
| Largest positive VaR contributor | `component_var_pct` | Risk contribution, not invested weight; negative hedging contributions can make positive shares exceed 100% |
| Residual financing | `financing_resilience.residual_margin` | Estimated loan after eligible liquid offsets; no sale, repayment or broker guarantee |
| Scenario loss and shock | `losses.stress.usd`, `stress_market_shock` | Hypothetical assumption and model result, not observed performance |
| Option-only expiry bounds | Existing `options_strategies.build_strategies` | Same underlying/expiry net groups, not original order pairings, stock-covered strategies or a single cross-expiry maximum |

Dollar loss displays require finite positive net-equity basis and the correct horizon. Missing/non-finite inputs remain unavailable; actual zero stays zero. Low/stale/unverified confidence suppresses ranked risk conclusions. Options always carry an account-risk delta-approximation limitation; expiry bounds do not capture early assignment, liquidity, execution or financing costs.

Strategy premiums explicitly distinguish entry, current mark, mixed and unavailable bases. A missing leg, invalid direction/cost relationship or invalid price cannot become a fabricated naked or bounded strategy. No payoff/premium basis means unavailable, **not** unbounded. Existing exact payoff calculations are reused; no browser financial calculations were introduced.

## Engineering boundaries

| Layer | Responsibility |
| --- | --- |
| `schemas/risk_check.py` | Finite typed result, closed status/unit enums, maximum three findings |
| `services/risk_check.py` | Pure projection of the report and reuse of existing exact expiry engine |
| `api/v1/risk.py` | Optional `include_copilot_check`; expected portfolio ID validation before fetching prices; one resolved context for computation |
| `services/copilot_scope.py` | Optimistic `/ask` identity and holdings/capital digest binding, verified before return; digest partitions response cache |
| `lib/use-copilot-thread.ts` | Foreground requests, abort/timeout semantics, runtime validation, bounded session history |
| `copilot-conversation.tsx` | One composer and timeline; keyed remount isolates users/portfolios |
| `copilot-answer.tsx`, `copilot-risk-check.tsx` | Input-free result renderers and progressive disclosure |

The new report fields are additive and opt-in. OpenAPI and generated TypeScript were regenerated. Obsolete `CopilotAsk` and its unused query hook were removed rather than retaining duplicate input/rendering paths. No dependency upgrade, database migration, real-holdings write, production action or new external integration was performed. The owner's mode-only change to `scripts/export_openapi.py` is preserved.

One non-queuing semaphore lane **per backend process** limits simultaneous foreground checks. This is not global distributed concurrency control. A busy worker responds 429; the UI prevents duplicate submission while a request is active. This does not claim server-side idempotency or exactly-once execution.

History keeps the latest 30 turns in sessionStorage, namespaced by user and portfolio and covered by the existing sign-out purge. Stored running turns become interrupted on reload, never auto-restarted. Closing/changing views stops client waiting; the old server calculation may finish. Completed turns can be reopened in the other view. Legacy variant-specific session messages are left untouched but are not silently imported into the new user-scoped schema (they lacked this explicit identity binding).

## Acceptance evidence

- Full backend suite: **1,194 passed, 1 skipped; coverage 88.76%** (85% required), including the final Beta-source regression.
- Root engine suite: **857 passed**.
- Frontend unit suite: **560 passed**; final edited component subset **19 passed**.
- Browser suite: **62 passed** across desktop Chromium and Pixel 7 emulation, including six new risk-check cases. Uses deterministic API fixtures, **not real production accounts**. Desktop/mobile viewport screenshots were inspected. Guards include one input, inline evidence/options, reload restoration, rejected wrong-book responses, no horizontal overflow, and mobile submit button above the navigation.
- Runtime tests additionally cover account/portfolio switch isolation, late responses, interrupted reload, double-click/stop, explicit-null portfolio binding, mid-answer input changes, and cache separation after holdings/capital changes.
- Financial regressions include one-day/21-day separation, nonpositive/non-finite basis, portfolio-vs-single-asset Beta, real-zero preservation, missing legs/basis, signed costs, same-expiry spread bounds, mixed/cross-expiry limits, and confidence gates.
- Black, Ruff, schema/core mypy, TypeScript, lint, production-like Next build, generated-contract check and diff whitespace checks passed in local verification.
- Offline grounding eval: **44 cases / 611 claims**, structural matching passed. This is deterministic-template evaluation, **not live-LLM faithfulness**. Existing fixture failure-path warnings remain visible; no claim of zero warnings.

## Explicit remaining work / release boundary

1. Phase 1B: foreground signed run records now implemented behind an off-by-default flag; database provisioning and real RLS acceptance remain pending. Bounded multi-step execution, semantic follow-up/clarification and execution recovery are still pending. Current `result_id` is only a display identifier; generation time is not a synchronized market quote. Optimistic before/after `/ask` digests are not a transaction or ABA-proof snapshot.
2. Same-snapshot hypothetical comparisons and version-bound confirmed plan saving, then research handoff and plan review. No new monitoring or scheduling here.
3. No additional option gamma/vega/time scenario engine integration in this check yet; existing separate scenario tools remain available. Complex unsupported structures must stay explicitly limited.
4. Before production release: review this UI transport/history change, run real authenticated staging flows on equity/options/margin portfolios and with the production data providers, measure cold/warm P50/P95, and authorize deployment separately. Mocked E2E success is not production proof.

## Methodology references

- [CFA Institute: Measuring and Managing Market Risk](https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/measuring-managing-market-risk) — distinctions between VaR, model limitations and stress analysis.
- [Options Industry Council: Delta](https://prd-web.optionseducation.org/advancedconcepts/delta) — delta sensitivity and its changing nature.
- [Options Industry Council: Delta, Gamma and Theta](https://www.optionseducation.org/videolibrary/the-greeks-i-delta-gamma-and-theta) — why first-order delta exposure is not complete option risk.
