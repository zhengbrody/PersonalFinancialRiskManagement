import { test, expect } from "./support/fixtures";
import { seedSession, E2E_USER } from "./support/auth";

const book = "33333333-3333-4333-8333-333333333333";
const side = { gross_assets: 13000, net_equity: 8000, cash: 1000, margin: 5000, leverage: 1.625, largest_position_weight: 0.77, annual_volatility: 0.2, var_1d_95_usd: 100, cvar_1d_95_usd: 180 };

test.beforeEach(async ({ page }) => {
  await seedSession(page);
  await page.route("**/api/v1/portfolios/me", (route) => route.fulfill({ json: {
    data: { user_id: E2E_USER.id, email: E2E_USER.email, portfolios: [{
      id: book, user_id: E2E_USER.id, name: "Comparison portfolio", holdings: { SGOV: { shares: 100 }, SPY: { shares: 10 } },
      is_default: true, margin_loan: 5000, contributed_capital: 7500, cash_balance: 1000, created_at: null, updated_at: null,
    }] }, error: null, meta: { request_id: "fixture" },
  } }));
});

test("clarify, reload, compare and revise inside the same Copilot window", async ({ page }) => {
  let calls = 0;
  await page.route("**/api/v1/copilot/compare-change", async (route) => {
    calls++;
    const assumptions = route.request().postDataJSON();
    expect(assumptions).toEqual({ expected_portfolio_id: book, ticker: "SGOV", amount: 1000, proceeds: "repay_margin" });
    await route.fulfill({ json: { data: {
      result_id: "44444444-4444-4444-8444-444444444444", portfolio_id: book, computed_at: "2026-09-06T12:00:00Z",
      snapshot_digest: "fixture", methodology_version: "reduce-close-v1", price_as_of: "2026-09-04", history_start: "2026-01-01", observations: 100,
      assumptions, sources: { SGOV: "fixture", SPY: "fixture" }, baseline: side,
      candidate: { ...side, gross_assets: 12000, margin: 4000, leverage: 1.5 },
      limitations: ["No guarantee against a margin call."],
    }, error: null, meta: { request_id: "test" } } });
  });
  await page.goto("/copilot");
  await page.getByRole("button", { name: "Test a change", exact: true }).click();
  await page.getByLabel("Held ticker").fill("SGOV");
  await page.getByLabel("Amount to reduce (USD)").fill("1000");
  await page.getByLabel("Use hypothetical proceeds to").selectOption("repay_margin");
  await page.reload();
  await expect(page.getByLabel("Held ticker")).toHaveValue("SGOV");
  expect(calls).toBe(0);
  await page.getByRole("button", { name: "Compare assumptions" }).click();
  const comparison = page.getByRole("region", { name: "Change comparison" });
  await expect(comparison).toBeVisible();
  await expect(comparison).toContainText("$4,000.00");
  await expect(comparison).toContainText("Net equity is conserved before costs");
  await expect(page.getByTestId("copilot-input")).toHaveCount(1);
  await comparison.getByText("Data, method and limits").click();
  await expect(comparison).toContainText("No guarantee against a margin call.");
  await comparison.getByRole("button", { name: "Revise assumption" }).click();
  await expect(page.getByLabel("Amount to reduce (USD)")).toHaveValue("1000");
  expect(calls).toBe(1);
  await expect(page).toHaveURL(/\/copilot$/);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("unsupported asset response keeps the form and does not fabricate a comparison", async ({ page }) => {
  await page.route("**/api/v1/copilot/compare-change", (route) => route.fulfill({ status: 422, json: {
    data: null, error: { code: "unsupported_comparison", message: "This book contains options. No positions were removed or treated as zero risk." }, meta: { request_id: "test" },
  } }));
  await page.goto("/copilot");
  await page.getByRole("button", { name: "Test a change", exact: true }).click();
  await page.getByLabel("Held ticker").fill("SGOV");
  await page.getByLabel("Amount to reduce (USD)").fill("1000");
  await page.getByRole("button", { name: "Compare assumptions" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "No positions were removed" })).toBeVisible();
  await expect(page.getByLabel("Held ticker")).toHaveValue("SGOV");
  await expect(page.getByRole("region", { name: "Change comparison" })).toHaveCount(0);
});
