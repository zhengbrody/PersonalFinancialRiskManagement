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

/** Real email/password sign-in; resolves once the SIGNED-IN home (Today)
 * renders — content an anonymous visitor never sees.
 *
 * History: this helper used to assert a redirect to /portfolios, which PR
 * #216 (2026-07-16) retired — login now lands on Today (`/`). Since `/` is
 * an auth-SWITCH (anon → marketing, signed-in → Today), the URL alone proves
 * nothing; assert on Today's signed-in-only copy instead. That stale URL
 * assertion burned the nightly red on 2026-07-17 — same failure class as the
 * earlier /portfolios-email assertion (PR #170): smoke tests must assert a
 * product SIGNAL, not an incidental route shape. */
async function login(page: Page): Promise<void> {
  await page.goto("/login");
  await page.locator('input[type="email"]').fill(EMAIL);
  await page.locator('input[type="password"]').fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  // Today's greeting subline renders only for a live Supabase session.
  await expect(page.getByText("Here's what to look at today.")).toBeVisible({
    timeout: 30_000,
  });
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
    // Identity proof: /settings is the ONE page that renders the account
    // email ("Signed in as …", settings/page.tsx) — and it renders it from a
    // real backend round-trip (/api/v1/billing/me), so this asserts the
    // JWT → backend → identity chain, not just the login redirect.
    //
    // History: this test previously asserted the email on /portfolios, which
    // never renders it (PR #140 removed email from the top bar; the page body
    // never had it) — the assertion was stale and burned the nightly red.
    // Assert identity where the product actually shows it.
    await page.goto("/settings");
    await expect(page.getByText(EMAIL).first()).toBeVisible({ timeout: 30_000 });
  });

  test("a signed-in data page loads through the real backend", async ({ page, baseURL }) => {
    // Login + (maybe) an authed write + a cold server-side market-data fetch.
    test.setTimeout(120_000);
    await login(page);

    // /score signed-in auto-scores the saved portfolio via the real backend
    // (/risk/score_from_active) — the rendered 0–1000 score IS the proof of
    // the real JWT → backend chain on a data route.
    //
    // History: this test previously asserted the account email was visible on
    // /score. PR #140 (privacy) removed email from the top bar, and /score
    // renders it nowhere else — the assertion silently went stale and the
    // nightly burned red for 15 nights. Assert the product-meaningful signal
    // (a real score through the real backend), not incidental PII display.
    await page.goto("/score");
    await expect(page).toHaveURL(/\/score/);

    // SELF-SEEDING: the bot keeps a 1-share SPY portfolio as its fixture.
    // Signed-in /score shows exactly one of two states: the score tile, or
    // the "Set up your portfolio" empty state (itself proof of an authed
    // backend round-trip that returned zero rows). On the empty state,
    // create the fixture through the REAL backend with the REAL session
    // token — an authed WRITE is an even stronger smoke — then reload.
    const emptyState = page.getByText("Set up your portfolio");
    const scoreTile = page.getByTestId("score-page-overall");
    await expect(emptyState.or(scoreTile).first()).toBeVisible({ timeout: 30_000 });

    if (await emptyState.isVisible()) {
      const token = await page.evaluate(() => {
        for (let i = 0; i < localStorage.length; i += 1) {
          const key = localStorage.key(i);
          if (key && key.startsWith("sb-") && key.endsWith("-auth-token")) {
            try {
              const parsed = JSON.parse(localStorage.getItem(key) ?? "{}");
              return parsed.access_token ?? parsed.currentSession?.access_token ?? null;
            } catch {
              return null;
            }
          }
        }
        return null;
      });
      expect(token, "Supabase access token must be in localStorage").toBeTruthy();

      const created = await page.request.post(`${baseURL}/api/v1/portfolios`, {
        headers: { Authorization: `Bearer ${token}` },
        data: {
          name: "E2E smoke fixture",
          holdings: { SPY: { shares: 1 } },
          is_default: true,
        },
      });
      expect(created.ok(), `portfolio create failed: ${created.status()}`).toBeTruthy();
      await page.reload();
    }

    await expect(scoreTile).toHaveText(/^\d{1,4}$/, { timeout: 60_000 });
  });
});
