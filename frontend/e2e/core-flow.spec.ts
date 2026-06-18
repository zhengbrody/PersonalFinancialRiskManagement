/**
 * Core auth-gated journey: signed-in → dashboard score → /score → copilot Q&A.
 *
 * This is exactly the path that's painful to unit-test (deep useActiveScore /
 * useRiskExplain / useLastSnapshot / streaming-copilot trees). Here it's driven
 * end-to-end against a mocked backend, asserting only user-visible behavior.
 */

import { test, expect } from "./support/fixtures";
import { seedSession } from "./support/auth";

test.describe("auth-gated core flow", () => {
  test.beforeEach(async ({ page }) => {
    await seedSession(page);
  });

  test("signed-in dashboard shows the active portfolio health score", async ({ page }) => {
    await page.goto("/");
    // The signed-in dashboard (not the marketing landing) renders the active score.
    await expect(page.getByTestId("dashboard-active-score")).toHaveText("782");
  });

  test("score page shows the signed-in health score", async ({ page }) => {
    await page.goto("/score");
    // The signed-in /score auto-scores the saved portfolio (no manual run needed).
    await expect(page.getByTestId("score-page-overall")).toHaveText("782");
  });

  test("copilot streams an answer to a question", async ({ page }) => {
    await page.goto("/copilot");

    await page.getByTestId("copilot-input").fill("Is my portfolio too risky?");
    await page.getByTestId("copilot-send").click();

    // The question echoes into the conversation…
    await expect(page.getByText("Is my portfolio too risky?")).toBeVisible();
    // …and the streamed (SSE) assistant answer arrives.
    await expect(page.getByText(/balanced for your current risk level/)).toBeVisible();
  });
});
