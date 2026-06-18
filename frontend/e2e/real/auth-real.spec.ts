/**
 * REAL auth smoke (gated, opt-in) — the one path the mocked suite can't cover:
 * a real /login form submission → a real Supabase session → a real protected
 * route served by the real backend.
 *
 * Runs against a DEPLOYED app (default production; override with E2E_BASE_URL)
 * using a REAL Supabase test user. It self-skips unless both credentials are
 * set, so it's a no-op locally and on any runner without secrets.
 *
 * Use a THROWAWAY test account — never the owner account, no sensitive data.
 * Credentials come from env (CI secrets); never hard-code them here.
 */

import { test, expect } from "@playwright/test";

const EMAIL = process.env.E2E_REAL_EMAIL ?? "";
const PASSWORD = process.env.E2E_REAL_PASSWORD ?? "";

test.describe("real auth smoke (live Supabase + backend)", () => {
  test.skip(
    !EMAIL || !PASSWORD,
    "Set E2E_REAL_EMAIL + E2E_REAL_PASSWORD and run with playwright.real.config.ts to enable.",
  );

  test("email/password login establishes a real session and reaches the signed-in app", async ({
    page,
  }) => {
    await page.goto("/login");

    await page.locator('input[type="email"]').fill(EMAIL);
    await page.locator('input[type="password"]').fill(PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();

    // A successful real sign-in redirects to /portfolios — a protected route an
    // anonymous visitor can't reach. Getting there proves the real session works.
    await expect(page).toHaveURL(/\/portfolios/, { timeout: 20_000 });

    // And the signed-in account menu surfaces the user's email.
    await expect(page.getByText(EMAIL).first()).toBeVisible();
  });
});
