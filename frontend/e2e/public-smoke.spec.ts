/**
 * Anonymous (no-auth) smoke: the public surface renders and does NOT leak the
 * signed-in dashboard. No session is seeded here.
 */

import { test, expect } from "./support/fixtures";

test.describe("public surface (anonymous)", () => {
  test("home renders the marketing landing, not the dashboard", async ({ page }) => {
    await page.goto("/");
    // The signed-in score must be absent…
    await expect(page.getByTestId("dashboard-active-score")).toHaveCount(0);
    // …and a sign-up entry point is present (href is stable regardless of copy).
    await expect(page.locator('a[href="/signup"]').first()).toBeVisible();
  });

  test("legal pages are reachable and money-free during the beta", async ({ page }) => {
    await page.goto("/legal/terms");
    await expect(page.getByRole("heading", { name: "Terms of Service" })).toBeVisible();
    await expect(page.getByText("Beta access")).toBeVisible();
  });

  test("public demo risk check loads", async ({ page }) => {
    await page.goto("/demo-risk-check");
    await expect(page).toHaveURL(/demo-risk-check/);
  });
});
