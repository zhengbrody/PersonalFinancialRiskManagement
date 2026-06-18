import { defineConfig, devices } from "@playwright/test";

/**
 * GATED real-auth smoke (e2e/real/*.real.spec.ts).
 *
 * Unlike the default suite (mocked, deterministic), this runs against a REAL
 * DEPLOYED app with a REAL Supabase test user — NO route mocks, NO seeded
 * session, NO local webServer. It validates the one thing the mocked suite
 * can't: the real /login → Supabase session → protected-route chain.
 *
 * It is OPT-IN: the spec self-skips unless E2E_REAL_EMAIL + E2E_REAL_PASSWORD
 * are set, so running it without credentials is a clean no-op. It is NOT wired
 * into PR CI — only the nightly/dispatch `e2e-real` workflow runs it.
 *
 * Target defaults to production; override with E2E_BASE_URL.
 */
const BASE_URL = process.env.E2E_BASE_URL || "https://mindmarket.app";

export default defineConfig({
  testDir: "./e2e/real",
  testMatch: /.*\.spec\.ts$/,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : [["list"]],
  timeout: 60_000,
  expect: { timeout: 15_000 },
  use: {
    baseURL: BASE_URL,
    trace: "on-first-retry",
    video: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  // No webServer: tests run against the already-deployed BASE_URL.
});
