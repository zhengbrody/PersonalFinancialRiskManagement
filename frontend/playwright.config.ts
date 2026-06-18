import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright E2E — deterministic + fully mocked.
 *
 * The Next.js frontend runs for real, but EVERY network dependency is stubbed
 * by Playwright route handlers (see e2e/support/mock-api.ts): no real backend,
 * Supabase, LLM, or paid API is ever hit. Auth is a seeded localStorage session
 * (e2e/support/auth.ts) — no real login, no personal session, no secret.
 *
 * The NEXT_PUBLIC_* below are DUMMY build-time values. They only need to
 *   (a) pass src/lib/env.ts validation (URL shape + ≥20-char key), and
 *   (b) point NEXT_PUBLIC_API_BASE_URL at this server so the `**\/api/v1/**`
 *       route glob intercepts the calls.
 * None of them is a real credential.
 */
const PORT = Number(process.env.E2E_PORT ?? 3100);
const BASE_URL = `http://localhost:${PORT}`;

const E2E_ENV: Record<string, string> = {
  // Drop `output: standalone` so `next start` serves cleanly (see next.config.mjs).
  E2E_BUILD: "1",
  NEXT_PUBLIC_API_BASE_URL: BASE_URL,
  NEXT_PUBLIC_SUPABASE_URL: "https://e2e.supabase.co",
  NEXT_PUBLIC_SUPABASE_ANON_KEY: "sb_publishable_e2e_playwright_dummy_key_000000",
  NEXT_PUBLIC_SITE_URL: BASE_URL,
  // Match production beta posture (billing UI hidden); avoids pricing surfaces.
  NEXT_PUBLIC_BILLING_ENABLED: "false",
};

export default defineConfig({
  testDir: "./e2e",
  testMatch: /.*\.spec\.ts/,
  // The gated real-auth smoke (e2e/real/*) runs via playwright.real.config.ts
  // against a deployed app — keep it out of this mocked, default suite.
  testIgnore: /real\//,
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : [["list"]],
  timeout: 30_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: BASE_URL,
    trace: "on-first-retry",
    video: "retain-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    // Mobile viewport + touch + mobile UA, still on the Chromium engine (no extra
    // browser download). Guards the retention-critical flow on a phone — the
    // target audience. (WebKit/iOS fidelity is a later add if iOS-specific bugs
    // surface; it would need `playwright install webkit`.)
    { name: "mobile-chrome", use: { ...devices["Pixel 7"] } },
  ],
  webServer: {
    // Build with the dummy NEXT_PUBLIC_* inlined, then serve. `next start` is
    // production-like + stable for E2E (vs `next dev`'s on-demand compile).
    command: `npm run build && npm run start -- -p ${PORT}`,
    url: BASE_URL,
    timeout: 180_000,
    reuseExistingServer: !process.env.CI,
    env: E2E_ENV,
  },
});
