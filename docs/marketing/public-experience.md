# Public product experience — 2026-09-10

## Scope and release posture

Local implementation, not deployed. Public homepage, Product, Demo, shared
marketing/auth chrome, SEO article template and metadata. Existing signed-in
Dashboard/auth routing, API contracts, financial engine and production data
are unchanged. The owner's four pre-existing modified OG/export files are
outside this change.

## Product story

Understand your risk before your next move. Show the task before the platform's
internal module names. A visitor can adjust a fictional position, compare cash
versus margin repayment, inspect assumptions, and then enter onboarding via the
existing allowlisted `/signup?next=%2Fportfolios%2Fnew` redirect.

The homepage no longer loads a ticker tape or macro panel before the product.
Markets remains reachable through contextual and footer links. The header uses
Product / How it works / Learn, Sign in, and Try demo. Mobile navigation keeps
Sign in inside the accessible menu. The sticky CTA waits until the entire
interactive hero has passed, not just the first button.

## Implementation boundaries

- `lib/marketing-sample.ts`: pure, bounded educational arithmetic.
- `marketing/sample-comparison.tsx`: one interactive component reused on Home,
  Product and Demo; no account calls, LLM, remote market data or persistence.
- `marketing/public-experience.module.css`: scoped layout and responsive rules.
- `lib/product-story.ts`: shared description and FAQ; visible answers and FAQ
  JSON-LD have a single source.
- Existing marketing shell, theme and auth components are reused. The obsolete
  homepage implementation, unreferenced live tape and scroll reveals, fake
  clickable preview, and now-unused Google display font are removed.
- SEO routes/canonicals remain intact. Articles show their actual answer before
  the workflow panel. No new schema claims, ratings, or promises of accuracy.

## Demo mathematics and limitations

Fictional starting account: growth stock $40,000, other stocks $60,000,
margin loan $20,000, net equity $80,000. Reduction is 0–50% of the growth
position, not of the entire account. Proceeds remain cash or repay debt.
Before-shock equity is conserved for both uses of proceeds.

Illustrative shock loss = (remaining growth value × 1.5 + other stock value)
× absolute market shock. Concentration divides growth value by stock value.
Cash and loan principal do not move under this immediate simplified shock.
Repayment changes financing, not the immediate loss versus holding the same
proceeds as cash. Interest, taxes, execution, options, changing correlations and
liquidation rules are excluded. This is NOT the production risk engine, VaR,
maximum loss or a forecast. Less exposure also means less upside participation.

No raw inputs are logged. The existing `demo_interacted` event is emitted once
per mounted demo, with only `{ kind: "sample_comparison" }`.

## Acceptance

- Exact independent arithmetic tests, equity conservation across every slider
  step and shock, zero adjustment, input rejection and equal immediate losses
  between the two financing choices.
- Component tests: real controls, reset, disclosures, FAQ parity, privacy-safe
  interaction event and sticky CTA viewport conditions.
- Existing home auth-switch and auth-redirect tests remain intact.
- Playwright: keyboard/radio/select interaction, signup handoff, SSR content,
  six public routes, canonical tags, 390px overflow guard, desktop/mobile
  screenshots in light/dark themes. External services are mocked.

Before release: run full frontend tests, lint/type checks and production build,
review the generated screenshots, then use the normal PR/deployment process.
No production release or real-user usability study is claimed by local tests.

Verified locally on 2026-09-10: 594 frontend tests across 116 files; 24 selected
Playwright tests across desktop/mobile; production Next build; TypeScript,
ESLint and `git diff --check` passed. Light/dark homepage and auth screenshots
were visually reviewed. Browser services were mocked, so these are not real
Supabase login or production-provider tests. No deployment performed.

## Capability alignment audit — 2026-09-10

Public descriptions must follow the implemented workflow, not combine the
strongest claims from different tools. `COMPARISON_CAPABILITIES` in
`frontend/src/lib/product-story.ts` supplies the same visible scope cards to
Home and Product. The shared five-stage story also feeds SEO pages. FAQ schema
continues to use exactly the visible FAQ data.

| Public capability | Implementation evidence | Required boundary |
| --- | --- | --- |
| Analyze stages | `frontend/src/components/analyze-workspace.tsx` | Overview, Drivers, Stress Test, Action Plan, History; recorded score history is not reconstructed brokerage performance. |
| Research-to-Test | `frontend/src/components/research-test-drawer.tsx` | Add/increase/reduce/replace equity positions; cash and option legs excluded; not full-account risk. |
| Copilot reduction | `frontend/src/components/copilot-change.tsx`, `backend/app/schemas/copilot_compare.py` | Held stock/ETF, USD amount, cash or margin repayment; supported US-listed/USD holdings; option legs unchanged. |
| Comparison risk method | Same comparison schema and result renderer | `historical_equity` versus `mixed_instant_stress`; mixed-account historical VaR/volatility unavailable, not zero. Option-only expiry bounds are not whole-account maximum loss. |
| Captured draft | `ComparisonReceipt.save_available`, `ConfirmComparison`, `CopilotChangeResult` | Explicit confirmation, eligible receipt, account revision and 15-minute age checks; original calculation, no fresh quotes or trades. |
| Later plan review | `backend/app/services/plan_review.py` | Compares supplied current/baseline metrics; not a background recomputation service. Captured comparison evidence is not automatically a comparable legacy review baseline. |
| Public sample | `frontend/src/lib/marketing-sample.ts` | Fictional local educational arithmetic, not the signed-in engine. Its percentage slider and selectable shock illustrate a concept, not the production USD-input form or its exact scenario set. |

No promise of autonomous monitoring, arbitrary options adjustments, universal
data coverage or AI infallibility. Capability cards remain expanded so the
limits are adjacent to the claims, not only hidden in disclosures. Save and
replay are conditional capabilities, not a claim that a production flag was
checked in this audit. This audit inspected source and local behavior only;
it did not deploy, change flags, or verify current production availability.

Alignment revision verified locally: 595 frontend tests / 116 files, 24 selected
desktop/mobile Playwright tests, production build, TypeScript, ESLint and diff
whitespace checks passed. The added regression checks the visible Research,
Copilot, capture-age and monitoring boundaries outside collapsed FAQs. Updated
desktop and mobile screenshots were inspected. External browser services remain
mocked; these checks do not certify the production backend or its feature flags.
