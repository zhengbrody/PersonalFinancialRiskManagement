/**
 * Copilot PR5 surfaces on /copilot: the proactive-insight strip (dismissable
 * by stable id), the six-section /ask answer (simulation visually marked as a
 * what-if), the preferences confirm flow, and a no-horizontal-overflow guard
 * (meaningful on the mobile-chrome project too).
 */

import { test, expect } from "./support/fixtures";
import { seedSession } from "./support/auth";

test.describe("copilot PR5 experience", () => {
  test.beforeEach(async ({ page }) => {
    await seedSession(page);
  });

  test("insight strip renders and dismissal hides the card", async ({ page }) => {
    await page.goto("/copilot");
    await expect(page.getByText("What changed for you")).toBeVisible();
    await expect(page.getByText(/100\.0% of your book/)).toBeVisible();
    await page.getByRole("button", { name: /Dismiss insight/ }).click();
    await expect(page.getByText(/100\.0% of your book/)).not.toBeVisible();
  });

  test("ask renders the six-section answer with a marked simulation", async ({ page }) => {
    await page.goto("/copilot");
    await page.getByLabel("Ask your Portfolio Copilot").fill("How risky is my portfolio?");
    await page.getByRole("button", { name: "Ask", exact: true }).click();

    await expect(page.getByText("Direct answer")).toBeVisible();
    await expect(page.getByText("Why this matters for your portfolio")).toBeVisible();
    await page.getByText("Evidence, assumptions & limits", { exact: true }).click();
    await expect(page.getByText("What would change this conclusion")).toBeVisible();
    await expect(page.getByText(/what-if · not a market fact/)).toBeVisible();
    await expect(
      page.getByText("Educational analysis, not financial advice."),
    ).toBeVisible();
    // Evidence row expands to the computing tool
    await page.getByText("Health score:", { exact: false }).first().click();
    await expect(page.getByText(/Portfolio health engine/)).toBeVisible();
  });

  test("preferences confirm flow saves and shows confirmation", async ({ page }) => {
    await page.goto("/copilot");
    await page.getByLabel("Risk tolerance").selectOption("3");
    await page.getByRole("button", { name: "Confirm preferences" }).click();
    await expect(page.getByText(/^Confirmed/)).toBeVisible();
  });

  test("no horizontal overflow on the copilot page", async ({ page }) => {
    await page.goto("/copilot");
    await expect(page.getByText("What changed for you")).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);
  });
});
