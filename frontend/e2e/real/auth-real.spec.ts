/**
 * REAL auth smoke (gated, opt-in) — the one path the mocked suite can't cover:
 * a real /login form submission → a real Supabase session → real protected
 * routes served by the real backend.
 *
 * Runs against a DEPLOYED app (default production; override with E2E_BASE_URL)
 * using a REAL Supabase test user. It self-skips unless both credentials are
 * set, so it's a no-op locally and on any runner without secrets.
 *
 * Use a THROWAWAY test account — never the owner account, no sensitive data.
 * Credentials come from env (CI secrets); never hard-code them here.
 */

import { test, expect, type Page } from "@playwright/test";

const EMAIL = process.env.E2E_REAL_EMAIL ?? "";
const PASSWORD = process.env.E2E_REAL_PASSWORD ?? "";

/** Real email/password sign-in; resolves once the protected /portfolios route
 * has loaded (proof the Supabase session is live). */
async function login(page: Page): Promise<void> {
  await page.goto("/login");
  await page.locator('input[type="email"]').fill(EMAIL);
  await page.locator('input[type="password"]').fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  // A successful real sign-in redirects to /portfolios — a protected route an
  // anonymous visitor can't reach.
  await expect(page).toHaveURL(/\/portfolios/, { timeout: 20_000 });
}

test.describe("real auth smoke (live Supabase + backend)", () => {
  test.skip(
    !EMAIL || !PASSWORD,
    "Set E2E_REAL_EMAIL + E2E_REAL_PASSWORD and run with playwright.real.config.ts to enable.",
  );

  test("email/password login establishes a real session and reaches the signed-in app", async ({
    page,
  }) => {
    await login(page);
    // The /portfolios page body greets the signed-in user by email
    // ("Signed in as …") — a signed-in-only render. (NOT the account menu:
    // PR #140 deliberately removed the email from the top bar.)
    await expect(page.getByText(EMAIL).first()).toBeVisible();
  });

  test("a signed-in data page loads through the real backend", async ({ page }) => {
    // Cold auto-scores can take a while (live market-data fetch server-side).
    test.setTimeout(90_000);
    await login(page);

    // /score signed-in auto-scores the saved portfolio via the real backend
    // (/risk/score_from_active) — the rendered 0–1000 score IS the proof of
    // the real JWT → backend chain on a data route. The e2e bot keeps a small
    // seeded portfolio, so this must always render.
    //
    // History: this test previously asserted the account email was visible on
    // /score. PR #140 (privacy) removed email from the top bar, and /score
    // renders it nowhere else — the assertion silently went stale and the
    // nightly burned red for 15 nights. Assert the product-meaningful signal
    // (a real score through the real backend), not incidental PII display.
    await page.goto("/score");
    await expect(page).toHaveURL(/\/score/);
    await expect(page.getByTestId("score-page-overall")).toHaveText(/^\d{1,4}$/, {
      timeout: 45_000,
    });
  });
});
