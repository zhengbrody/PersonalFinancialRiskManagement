/**
 * Mobile layout guard: at a 390px viewport (iPhone-class), no consumer surface
 * may scroll the PAGE horizontally. Inner `overflow-x:auto` containers (wide
 * tables) are allowed — those don't widen the document, so this catches only
 * true page-level overflow. Covers the marketing pages, the auth forms, and the
 * signed-in PortfolioForm (the mobile-responsive fix).
 */

import { test, expect } from "./support/fixtures";
import { seedSession } from "./support/auth";

test.use({ viewport: { width: 390, height: 844 } });

async function pageOverflowPx(page: import("@playwright/test").Page): Promise<number> {
  return page.evaluate(
    () =>
      document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
}

test.describe("no horizontal scroll at 390px", () => {
  for (const path of ["/", "/demo-risk-check", "/login", "/signup"]) {
    test(`public ${path}`, async ({ page }) => {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      expect(await pageOverflowPx(page)).toBeLessThanOrEqual(1);
    });
  }

  test("signed-in /portfolios/new (PortfolioForm)", async ({ page }) => {
    await seedSession(page);
    await page.goto("/portfolios/new");
    await expect(page.getByRole("heading", { name: "New portfolio" })).toBeVisible();
    expect(await pageOverflowPx(page)).toBeLessThanOrEqual(1);
  });
});
