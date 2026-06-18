# End-to-end tests (Playwright)

Browser E2E for the **auth-gated core journey** that's impractical to unit-test
(deep `useActiveScore` / `useRiskExplain` / streaming-copilot trees). The suite
is **deterministic and fully mocked** — it never touches the real backend,
Supabase, an LLM, or any paid/streaming API.

## How it works

- **App under test:** the real Next.js frontend, built + served by Playwright's
  `webServer` (`next build && next start`) on port `3100`.
- **Network:** every `/api/v1/*` call is fulfilled by Playwright route handlers
  (`e2e/support/mock-api.ts`) with canned, schema-valid envelopes. External hosts
  (Supabase auth, PostHog, Sentry) are stubbed too — nothing leaves the machine.
- **Auth:** no real login. `e2e/support/auth.ts` seeds a fake Supabase session
  into `localStorage`; the app's `getSession()` resolves it locally (no network),
  so the app behaves as signed-in. No real password/token/secret, no dependency
  on your personal session.

## Run it

```bash
cd frontend
npm ci                       # if you haven't already
npm run e2e:install          # one-time: download the Chromium browser
npm run test:e2e             # headless (builds + serves + runs)
npm run test:e2e:headed      # watch it in a real browser
npm run test:e2e:ui          # Playwright's interactive UI mode
```

First run builds the app (~1 min). Locally, an already-running dev server on
`:3100` is reused (`reuseExistingServer`); in CI a fresh server is always built.

## Env vars

No real secrets. `playwright.config.ts` injects **dummy** build-time values
(`NEXT_PUBLIC_API_BASE_URL` → the test server, plus throwaway
`NEXT_PUBLIC_SUPABASE_URL` / `_ANON_KEY` that only satisfy `src/lib/env.ts`
validation). Override the port with `E2E_PORT` if `3100` is taken.

## Coverage

`core-flow.spec.ts` (signed-in, seeded session):
- **Dashboard** (`/`) renders the active **portfolio health score**.
- **`/score`** auto-scores the saved portfolio and shows the score.
- **`/copilot`** sends a question and renders the **streamed (SSE)** answer.

`public-smoke.spec.ts` (anonymous, no session):
- `/` shows the marketing landing, **not** the dashboard (no data leak).
- `/legal/terms` is reachable and shows the free-beta ("Beta access") copy.
- `/demo-risk-check` loads.

## Not covered (yet)

- Real signup/login against Supabase, OAuth, password reset (would need a test
  Supabase project + seeded users; out of scope for a deterministic suite).
- Real backend/LLM responses, billing/Stripe checkout, multi-portfolio CRUD.
- Mobile viewports / visual regression.

These are intentional: this suite proves the **wiring** of the core journey
(auth → data → render → interact) without flaky external dependencies.
