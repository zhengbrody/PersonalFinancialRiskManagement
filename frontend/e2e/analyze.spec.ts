/**
 * The unified /analyze workspace: signed-in → 5 URL-tabbed stages, tab drives
 * ?view=, and the Action Plan stage surfaces saved plans. Driven end-to-end
 * against the mocked backend (the deep useActiveScore / report / plans trees
 * are painful to unit-test).
 */

import { test, expect } from "./support/fixtures";
import { seedSession } from "./support/auth";

test.describe("analyze workspace", () => {
  test.beforeEach(async ({ page }) => {
    await seedSession(page);
  });

  test("renders the 5 stages", async ({ page }) => {
    await page.goto("/analyze");
    for (const label of ["Overview", "Drivers", "Stress Test", "Action Plan", "History"]) {
      await expect(page.getByRole("tab", { name: label })).toBeVisible();
    }
  });

  test("switching a tab updates ?view= and shows the stage", async ({ page }) => {
    await page.goto("/analyze?view=overview");
    await page.getByRole("tab", { name: "Action Plan" }).click();
    await expect(page).toHaveURL(/view=plan/);
    // The Action Plan stage's saved-plans card is visible (empty state here).
    await expect(page.getByText("Saved risk plans")).toBeVisible();
    await expect(page.getByText(/No saved plans yet/)).toBeVisible();
  });

  test("deep-links straight to a stage via ?view=", async ({ page }) => {
    await page.goto("/analyze?view=stress");
    await expect(page.getByText("What-if lab")).toBeVisible();
    await expect(page.getByText(/Simulation only · holdings unchanged/)).toBeVisible();
  });
});
