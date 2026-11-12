/**
 * Stress Lab on /quant, end to end against a mocked backend.
 *
 * The response fixture is a REAL engine run (live market data, a levered book
 * with two option legs) captured to e2e/fixtures/factor-stress.json — so the
 * charts are exercised with realistic shapes, not hand-typed numbers.
 */

import fs from "node:fs";
import path from "node:path";
import { test, expect } from "./support/fixtures";
import { seedSession } from "./support/auth";

const fixture = JSON.parse(
  fs.readFileSync(path.join(__dirname, "fixtures", "factor-stress.json"), "utf8"),
);

test.describe("stress lab", () => {
  test.beforeEach(async ({ page }) => {
    await seedSession(page);
    await page.route("**/api/v1/risk/factor_stress", async (route) => {
      const body = route.request().postDataJSON() ?? {};
      const data = { ...fixture, horizon_weeks: body.horizon_weeks ?? 2 };
      if (body.custom_shocks) {
        const base = fixture.scenarios[0];
        data.scenarios = [
          ...fixture.scenarios,
          { ...base, id: "custom", label: "Your scenario", kind: "custom", source: "Shocks you entered." },
        ];
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ data, error: null, meta: { request_id: "e2e-stress" } }),
      });
    });
  });

  test("runs on open, and selecting a scenario changes the detail", async ({ page }) => {
    await page.goto("/quant");
    const lab = page.getByTestId("stress-lab");
    await expect(lab).toBeVisible();
    await expect(page.getByRole("tab", { name: "Stress Lab" })).toHaveAttribute("aria-selected", "true");

    const detail = page.getByTestId("stress-scenario-detail");
    await expect(detail).toContainText("Equity crash");
    await page.getByRole("button", { name: /COVID-19 crash/ }).click();
    await expect(detail).toContainText("COVID-19 crash");
    // A historical replay carries a day-by-day path and the no-model cross-check.
    await expect(page.getByTestId("stress-episode-path")).toBeVisible();
    await expect(page.getByTestId("stress-realised-check")).toBeVisible();
    await page.getByRole("button", { name: "Margin used", exact: true }).click();
    await expect(page.getByRole("img", { name: /Modelled margin through COVID-19 crash/ })).toBeVisible();
  });

  test("regime, horizon and a custom scenario are interactive", async ({ page }) => {
    await page.goto("/quant");
    await expect(page.getByTestId("stress-lab")).toBeVisible();

    await page.getByRole("button", { name: "Calm", exact: true }).click();
    await expect(page.getByRole("img", { name: /Simulated calm loss distribution/ })).toBeVisible();

    const refetch = page.waitForRequest(
      (r) => r.url().includes("/risk/factor_stress") && r.postDataJSON()?.horizon_weeks === 4,
    );
    await page.getByRole("button", { name: "4 weeks", exact: true }).click();
    await refetch;

    await page.getByLabel("Equity move in %").fill("-25");
    await page.getByLabel("Vol move in × VIX").fill("2");
    const custom = page.waitForRequest((r) => {
      const b = r.url().includes("/risk/factor_stress") ? r.postDataJSON() : null;
      return !!b?.custom_shocks && Math.abs(b.custom_shocks.equity + 0.25) < 1e-9;
    });
    await page.getByRole("button", { name: "Run my scenario" }).click();
    const sent = (await custom).postDataJSON();
    expect(sent.custom_shocks.vol).toBeCloseTo(Math.log(2), 9);
    await expect(page.getByTestId("stress-scenario-detail")).toContainText("Your scenario");
  });

  test("selecting a holding shows where its loadings come from", async ({ page }) => {
    await page.goto("/quant");
    await page.getByRole("button", { name: "Inspect NVDA" }).click();
    await expect(page.getByTestId("stress-holding-detail")).toContainText("NVDA");
    await expect(page.getByTestId("stress-holding-detail")).toContainText(/weeks of returns/);
  });

  test("no horizontal overflow, and a full-page capture", async ({ page }, info) => {
    await page.goto("/quant");
    await expect(page.getByTestId("stress-lab")).toBeVisible();
    await page.getByRole("button", { name: /COVID-19 crash/ }).click();
    await page.waitForTimeout(400);
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);
    await page.screenshot({ path: info.outputPath("stress-lab.png"), fullPage: true });
  });
});
