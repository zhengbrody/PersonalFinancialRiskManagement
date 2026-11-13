/**
 * Crisis replay and Model accuracy tabs on /quant. Fixtures are REAL outputs:
 * a replay of a real book on live market data, and the committed validation
 * report.
 */

import fs from "node:fs";
import path from "node:path";
import { test, expect } from "./support/fixtures";
import { seedSession } from "./support/auth";

const load = (name: string) =>
  JSON.parse(fs.readFileSync(path.join(__dirname, "fixtures", name), "utf8"));
const replay = load("crisis-replay.json");
const validation = load("stress-validation.json");
const stress = load("factor-stress.json");

const ok = (data: unknown) => ({
  status: 200,
  contentType: "application/json",
  body: JSON.stringify({ data, error: null, meta: { request_id: "e2e" } }),
});

test.describe("crisis replay and model accuracy", () => {
  test.beforeEach(async ({ page }) => {
    await seedSession(page);
    await page.route("**/api/v1/risk/factor_stress", (r) => r.fulfill(ok(stress)));
    await page.route("**/api/v1/risk/crisis_replay", (r) => r.fulfill(ok(replay)));
    await page.route("**/api/v1/risk/stress_validation", (r) => r.fulfill(ok(validation)));
  });

  test("replay: select an episode, see labelled holdings and peak stress", async ({ page }, info) => {
    await page.goto("/quant");
    await page.getByRole("tab", { name: "Crisis replay" }).click();
    await expect(page.getByTestId("crisis-replay")).toBeVisible();
    const detail = page.getByTestId("crisis-replay-detail");
    await expect(detail).toContainText("COVID-19 crash");

    await page.getByRole("button", { name: "Global Financial Crisis" }).click();
    await expect(detail).toContainText("Global Financial Crisis");
    // RDDT did not exist in 2008: reconstructed, and it says from what.
    const rddt = page.getByTestId("replay-holding-RDDT");
    await expect(rddt).toContainText("Reconstructed");
    await expect(rddt).toContainText(/estimated from/);
    await expect(page.getByTestId("replay-holding-AAPL")).toContainText("Observed");
    await expect(page.getByTestId("crisis-peak-stress")).toContainText("Worst single day");
    await expect(page.getByTestId("crisis-correlation")).toContainText("Between your holdings");
    // The unpriced holding and the options are named, not dropped.
    await expect(page.getByTestId("crisis-replay")).toContainText("No price is available for ZZZZQ");

    await page.getByRole("button", { name: "Drawdown", exact: true }).click();
    await expect(page.getByRole("img", { name: /Drawdown through Global Financial Crisis/ })).toBeVisible();
    await page.getByRole("button", { name: "Reconstructed", exact: true }).click();
    await expect(page.getByTestId("replay-holding-AAPL")).toHaveCount(0);

    await page.waitForTimeout(300);
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);
    await page.screenshot({ path: info.outputPath("crisis-replay.png"), fullPage: true });
  });

  test("model accuracy: headline, baselines, hash check and filters", async ({ page }, info) => {
    await page.goto("/quant");
    await page.getByRole("tab", { name: "Model accuracy" }).click();
    const panel = page.getByTestId("stress-validation");
    await expect(panel).toBeVisible();
    await expect(page.getByTestId("validation-models")).toContainText("Assume beta = 1");
    await expect(page.getByTestId("validation-provenance")).toContainText(validation.content_sha256);
    await expect(page.getByTestId("validation-provenance")).toContainText("Contents match the report hash");

    const rows = page.getByTestId("validation-rows").locator("tbody tr");
    const all = await rows.count();
    await expect(page.getByTestId("validation-rows")).not.toContainText("picked with hindsight");
    await page.getByRole("button", { name: "Show", exact: true }).click();
    await expect(page.getByTestId("validation-rows")).toContainText("picked with hindsight");
    expect(await rows.count()).toBeGreaterThan(all);
    await page.getByLabel("Episode").selectOption("covid_2020");
    await expect(rows.first()).toContainText("COVID-19 crash");

    await page.waitForTimeout(300);
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);
    await page.screenshot({ path: info.outputPath("model-accuracy.png"), fullPage: true });
  });

  test("model accuracy is public: it renders without a portfolio call", async ({ page }) => {
    let replayCalls = 0;
    await page.route("**/api/v1/risk/crisis_replay", (r) => {
      replayCalls += 1;
      return r.fulfill(ok(replay));
    });
    await page.goto("/quant");
    await page.getByRole("tab", { name: "Model accuracy" }).click();
    await expect(page.getByTestId("stress-validation")).toBeVisible();
    expect(replayCalls).toBe(0);
  });
});
