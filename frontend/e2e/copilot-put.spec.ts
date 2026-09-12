import { test, expect } from "./support/fixtures";
import { seedSession, E2E_USER } from "./support/auth";
import result from "../src/test-fixtures/copilot-put.json";

const envelope = (data: unknown) => ({ data, error: null, meta: { request_id: "fixture" } });

test("cash-secured put stays hypothetical in the existing conversation", async ({ page }) => {
  await seedSession(page);
  await page.route("**/api/v1/portfolios/me", route => route.fulfill({ json: envelope({
    user_id: E2E_USER.id, email: E2E_USER.email, portfolios: [{
      id: result.portfolio_id, user_id: E2E_USER.id, name: "Cash put portfolio",
      holdings: { SGOV: { shares: 100 } }, is_default: true, cash_balance: 11000,
      margin_loan: 0, contributed_capital: 11000, created_at: null, updated_at: null,
    }],
  }) }));
  await page.route("**/api/v1/copilot/ask", route => route.fulfill({ json: envelope({
    intent: "explain_metric", tickers: [], answer_markdown: "A put has assignment obligations.",
    evidence: [], data_only: true, decision_support: {
      version: 1, task: { kind: "explanation", goal: null, missing_inputs: [], confirmed_constraints: {} },
      coverage: "explained", methods: [], limitations: [], save_available: false,
      candidate_comparison_available: false, cash_secured_put_available: true,
    },
  }) }));
  await page.route("**/api/v1/copilot/cash-secured-put", route => {
    expect(route.request().postDataJSON()).toEqual(result.assumptions);
    return route.fulfill({ json: envelope(result) });
  });
  await page.goto("/copilot");
  await expect(page.getByRole("button", { name: "Cash put portfolio", exact: true })).toBeVisible();
  await page.getByTestId("copilot-input").fill("What is a cash secured put?");
  await page.getByTestId("copilot-send").click();
  await page.getByText("Test a cash-secured Put").click();
  await expect(page.getByRole("button", { name: "Calculate put scenario" })).toBeDisabled();
  for (const [label, value] of Object.entries({
    "Put underlying": "SPY", "Put expiry": "2026-10-16", "Strike (USD per share)": "100",
    "Assumed premium (USD per share)": "2", "Assumed underlying price (USD)": "105",
    "Estimated total fees (USD)": "1", "Other cash holds, excluding listed put collateral (USD)": "0",
    "Cash buffer to preserve (USD)": "1000",
  })) await page.getByLabel(label, { exact: true }).fill(value);
  for (const box of await page.getByRole("checkbox").all()) await box.check();
  await page.getByRole("button", { name: "Calculate put scenario" }).click();
  await expect(page.getByText("Cash covered under your confirmed assumptions")).toBeVisible();
  await expect(page.getByText("-$1.00", { exact: true })).toBeVisible();
  await expect(page.getByTestId("copilot-input")).toHaveCount(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole("region", { name: "Cash-secured put result" }).screenshot({ path: test.info().outputPath("put-scenario.png") });
});
