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

**Both specs run on two projects** — `chromium` (Desktop Chrome) and
`mobile-chrome` (Pixel 7: mobile viewport + touch + mobile UA, still the Chromium
engine). The mobile run guards the retention-critical flow on a phone — clicks go
through Playwright's tap-actionability checks, so an off-screen / overlapped
control on a small viewport fails the test.

## Real-auth smoke (gated, opt-in)

A separate, **non-mocked** smoke (`e2e/real/auth-real.spec.ts`, run via
`playwright.real.config.ts`) logs a **real Supabase test user** into the
**deployed** app and verifies the real `/login` → session → protected-route
chain — the one thing the mocked suite can't. It is **not** part of PR CI; it
runs only via the `E2E (real auth, nightly)` workflow (schedule + manual
dispatch) and **self-skips unless credentials are set**.

```bash
# Run it locally against production (or set E2E_BASE_URL to a preview):
E2E_REAL_EMAIL='test@example.com' E2E_REAL_PASSWORD='…' npm run test:e2e:real
# Without those two env vars it skips cleanly (no-op).
```

**To enable in CI (one-time, owner):**
1. Create a **throwaway test user** in the Supabase project the deployed app
   uses (Authentication → Users → Add user, email confirmed). NOT the owner
   account; no sensitive data. (A separate Supabase *project* is **not** needed
   for this smoke — it runs against the live app, which uses the live project.)
2. Add repo **Secrets** `E2E_REAL_EMAIL` + `E2E_REAL_PASSWORD`.
3. (Optional) repo **Variable** `E2E_BASE_URL` to target a non-prod URL.
4. (Optional) seed that user a small portfolio so the score surfaces render.

## Not covered (yet)

- OAuth / password-reset / signup flows; multi-portfolio CRUD; billing/Stripe
  checkout; real LLM-response assertions (non-deterministic by nature).
- True iOS/Safari rendering (mobile runs on Chromium; WebKit would need
  `playwright install webkit`) and visual-regression snapshots.

These are intentional: this suite proves the **wiring** of the core journey
(auth → data → render → interact) without flaky external dependencies.
