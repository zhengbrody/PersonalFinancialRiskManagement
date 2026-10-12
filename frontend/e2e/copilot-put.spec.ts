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
      candidate_comparison_available: false, cash_secured_put_available: true, cash_secured_put_save_available: true,
    },
  }) }));
  await page.route("**/api/v1/copilot/cash-secured-put", route => {
    expect(route.request().postDataJSON()).toEqual(result.assumptions);
    return route.fulfill({ json: envelope({ ...result, receipt: { record: "signed fixture", signature: "a".repeat(64), save_available: true } }) });
  });
  const saved = { plan_id: result.result_id, portfolio_id: result.portfolio_id, confirmed_at: result.computed_at, result };
  await page.route("**/api/v1/copilot/put-plans/*/confirm", route => {
    expect(route.request().postDataJSON().confirmed).toBe(true);
    return route.fulfill({ json: envelope(saved) });
  });
  await page.route("**/api/v1/copilot/put-plans/history?*", route => route.fulfill({ json: envelope({ plans: [saved], next_cursor: null, skipped_records: 0 }) }));
  await page.route("**/api/v1/copilot/put-plans/*/review", route => route.fulfill({ json: envelope({
    plan_id: saved.plan_id, portfolio_id: saved.portfolio_id, reviewed_at: result.computed_at,
    verdict: "requires_recalculation", changed_fields: ["cash_balance"], reasons: ["Account cash changed."],
    live_quote_checked: false, holdings_changed_by_review: false,
  }) }));
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
  for (const box of await page.getByRole("checkbox").all()) { if (await box.isEnabled()) await box.check(); }
  await page.getByRole("button", { name: "Calculate put scenario" }).click();
  await expect(page.getByText("Cash covered under your confirmed assumptions")).toBeVisible();
  await expect(page.getByText("-$1.00", { exact: true })).toBeVisible();
  await expect(page.getByTestId("copilot-input")).toHaveCount(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByLabel("Save this original hypothetical Put calculation as a draft RiskPlan. This does not place a trade.").check();
  await page.getByRole("button", { name: "Confirm save Put plan" }).click();
  await expect(page.getByText("Original calculation saved. No holdings were changed.")).toBeVisible();
  await page.getByText(/SPY Put · saved/).click();
  await page.getByText("Original inputs & funding").click();
  await expect(page.getByText("Premium per share", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Review current assumptions" }).click();
  await expect(page.getByText("Recalculation required")).toBeVisible();
  await page.getByRole("button", { name: "Load saved Put plans" }).click();
  await expect(page.getByText(/Verified history in stable plan order/)).toBeVisible();
  await page.getByRole("region", { name: "Saved put plans" }).screenshot({ path: test.info().outputPath("saved-put-review.png") });
  await page.getByRole("region", { name: "Cash-secured put result" }).screenshot({ path: test.info().outputPath("put-scenario.png") });
});
