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
    // The signed-in account menu surfaces the user's email.
    await expect(page.getByText(EMAIL).first()).toBeVisible();
  });

  test("a signed-in data page loads through the real backend", async ({ page }) => {
    await login(page);

    // /score is a protected data page: signed-in it auto-scores the saved
    // portfolio via the real backend (/risk/score_from_active). Reaching it as
    // the signed-in user (account email present, not redirected to /login)
    // proves the real JWT → backend chain on a data route.
    await page.goto("/score");
    await expect(page.getByText(EMAIL).first()).toBeVisible();

    // If the test user HAS a saved portfolio, a real 0–1000 score renders —
    // assert it's a real number. Harmless when there's no portfolio: the score
    // tile is simply absent, so this block is skipped. (Seed the test user a
    // small portfolio to make this assertion always fire.)
    const score = page.getByTestId("score-page-overall");
    if ((await score.count()) > 0) {
      await expect(score).toHaveText(/^\d{1,4}$/);
    }
  });
});
