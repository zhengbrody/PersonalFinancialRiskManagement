# Workspace UI/UX: clarity before complexity

## Design intent

Learn from retail platforms' clear hierarchy and direct navigation, and from
institutional tools' portfolio context, risk drivers, scenarios and auditability.
This is an original MindMarket interface, not a copy of another brand or a claim
to offer institutional capabilities we do not implement.

Reference research:
- [Robinhood Legend layouts](https://robinhood.com/us/en/support/articles/layouts-on-legend/): make a workspace easy to navigate and organize.
- [Aladdin Risk](https://www.blackrock.com/aladdin/platforms/products/aladdin-risk): connect whole-portfolio analysis with risk exploration.
- [MSCI RiskMetrics stress testing](https://www.msci.com/www/product-documentation/riskmetrics-riskmanager-stress/0163884132): make scenario consequences understandable.

## Implemented scope

| Surface | User benefit | Architecture |
| --- | --- | --- |
| Shared shell | Always know where you are; Holdings is no longer hidden in Account | One desktop/mobile navigation model with exact route matching |
| Mobile | Five persistent destinations, usable touch targets, no competing floating chat button | Safe-area bottom navigation; Copilot remains a full page; feedback moves into document flow |
| Today | One deterministic next action and a legible health score | Existing priority logic unchanged; optional setup and market disclosures |
| Analyze | Understand, investigate, simulate, plan, review | Existing five URL-backed lazy stages; explicit next-stage navigation and browser Back support |
| Overview | Distinguish account equity, historical volatility, leverage and health score | Pure presentation of the existing typed response; missing values stay unavailable |
| Holdings | Primary actions remain visible; exports/deletion are secondary | Native disclosure; destructive confirmation preserved |
| Research / Copilot | Shorter, consistent introductions explaining what to do | Existing research, evidence and conversation flows retained |
| Shared tables / gauge | Readable rows, keyboard sorting, accurate scale positioning | Native sort buttons, aria-sort and accessible meter; no new package |

The weakest-dimension callout now reads `dimensions`, the public API field, instead
of the obsolete `dimension_scores`. Gauge ticks are aligned at 40%, 65%, 85%,
not equally spaced. Neither change modifies the risk engine.

## Guardrails

- No new financial calculations, generated performance charts, or invented live data.
- No reinterpretation of current-mix historical return as account YTD.
- No gross-assets fallback when net equity is unknown.
- No trade execution, holdings mutation, backend contract or database changes.
- Existing active-portfolio switching and unsaved-work safeguards remain intact.
- Risk labels and colors remain distinct from navigation accent colors.
- Marketing remains on its separate shell and palette. Shared type/cards are intentionally reusable.
- No added application dependencies. The owner's `scripts/export_openapi.py` change is untouched.

## Validation and handoff

Run `npm test`, `npm run lint`, `npx tsc --noEmit`, and
`npx playwright test --workers=2` inside `frontend`.
The browser suite builds the actual Next.js app with dummy configuration, then
uses isolated fixture API responses. Screenshots are written under
`frontend/test-results/workspace-design-*` for light/dark desktop/mobile views.
These are layout evidence, **not production-account verification**.

The shared E2E portfolio fixture was missing required envelope/row fields and the
score-change endpoint. Those fixtures are corrected; the design tests wait for a
loaded portfolio and score before capturing, rather than accepting skeleton screens.

Release separately through the existing CI/image deployment process. This local
UI implementation does not itself establish that production has been updated.

Local validation (2026-09-05): 558 unit tests across 116 files passed; 50 browser
tests passed across Chromium desktop and mobile, including 360/390/768/1024px
navigation checks. ESLint, TypeScript, production-mode Next.js build and
`git diff --check` passed. Loaded Today/Analyze/Holdings screenshots were visually
reviewed in light and dark themes. No browser page errors in the captured flows.

## Independent acceptance review — 2026-09-05

Four interaction defects were reproduced with failing tests and repaired:

| Finding | Repair and regression coverage |
| --- | --- |
| Landscape navigation's final action extended below the viewport (421px, bottom navigation starts at 295px) | Scrollable, viewport/safe-area-bounded disclosures; menu and portfolio-management actions remain reachable at 800×360; compact menu targets are at least 44px |
| Escape from the portfolio list lost keyboard focus | Shared `useDismiss` optionally restores opener focus on Escape only; selection also restores focus; outside clicks retain their target |
| An open desktop Copilot continued covering the compact workspace | Panel and launcher share the CSS desktop breakpoint; returning to desktop retains the conversation; dragged panels reclamp after maximize and resize |
| Metadata rerenders reset the user's focused portfolio option | Stable callback ref focuses the active option only on mount; ArrowDown selection survives rerenders |

Navigation disclosures use native links/buttons, not incomplete ARIA application
menus. The portfolio management link is outside the listbox's options. No new
dependency or parallel state-management implementation was introduced.

Final gates: **560 unit tests / 116 files**, **56 Chromium desktop/mobile browser
tests**, TypeScript, ESLint, production-mode Next.js build and diff whitespace
checks passed. Refreshed light/dark desktop/mobile screenshots were reviewed.
The backend, risk formulas, OpenAPI, generated API types and dependency lockfile
have no changes from the base of this UI branch.

Acceptance is scoped to this UI change and the exercised fixture-driven flows.
It is not a whole-platform security/financial-model certification or a guarantee
of zero bugs. Safari/iOS, real broker data, live-account authorization and a
deployed production build were not revalidated here. Existing build/test runtime
warnings (Next lint deprecation, Node flags, server-side chart measurement) are
not hidden or treated as UI failures. Production release remains a separate step.
