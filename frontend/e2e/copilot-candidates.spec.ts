import { test, expect } from "./support/fixtures";
import { seedSession, E2E_USER } from "./support/auth";

const book = "33333333-3333-4333-8333-333333333333";
const side = { gross_assets: 13000, net_equity: 8000, cash: 1000, margin: 5000, leverage: 1.625, largest_position_weight: 0.77, annual_volatility: 0.2, var_1d_95_usd: -100, cvar_1d_95_usd: -180 };
const envelope = (data: unknown) => ({ data, error: null, meta: { request_id: "fixture" } });

test("confirmed candidates and retrieval stay in one window", async ({ page }) => {
  await seedSession(page);
  await page.route("**/api/v1/portfolios/me", route => route.fulfill({ json: envelope({ user_id: E2E_USER.id, email: E2E_USER.email,
    portfolios: [{ id: book, user_id: E2E_USER.id, name: "Comparison portfolio", holdings: { SPY: { shares: 10 } }, is_default: true,
      margin_loan: 5000, cash_balance: 1000, contributed_capital: 7500, created_at: null, updated_at: null }] }) }));
  await page.route("**/api/v1/copilot/ask", route => route.fulfill({ json: envelope({ intent: "action_plan", tickers: [],
    answer_markdown: "Confirm your goal and budget. Selling puts is not stable income.", evidence: [], data_only: true,
    decision_support: { version: 1, task: { kind: "candidate_request", goal: null, missing_inputs: ["goal", "budget"], confirmed_constraints: {} },
      coverage: "insufficient_data", methods: [], limitations: [], save_available: false, candidate_comparison_available: true } }) }));
  let starts = 0;
  let stored: unknown;
  await page.route("**/api/v1/copilot/decision-runs", route => {
    starts++;
    const body = route.request().postDataJSON();
    expect(body.task.confirmed).toBe(true);
    expect(body.task.goal).toBe("reduce_margin");
    const result = { result_id: "44444444-4444-4444-8444-444444444444", portfolio_id: book, computed_at: "2026-09-11T12:00:00Z", snapshot_digest: "fixture",
      methodology_version: "reduce-close-v1", assumptions: { expected_portfolio_id: book, ticker: "SPY", amount: 500, proceeds: "repay_margin" },
      price_as_of: "2026-09-11", history_start: "2026-01-01", observations: 100, sources: { SPY: "fixture" }, baseline: side,
      candidate: { ...side, gross_assets: 12500, margin: 4500 }, limitations: ["No new option or broker buying power is calculated."] };
    stored = { id: body.id, portfolio_id: book, state: "completed", error_code: null, attempts: 1, step: "done", result: {
      snapshot_id: body.id, portfolio_id: book, computed_at: "2026-09-11T12:00:00Z", task: body.task, baseline: side, candidates: [result],
      preferred_result_id: null, coverage: "evaluated", judgment: "Inspect tradeoffs against keeping the portfolio.", excluded: {}, limitations: [] } };
    return route.fulfill({ json: envelope(stored) });
  });
  await page.route("**/api/v1/copilot/decision-runs/*", route => route.fulfill({ json: envelope(stored) }));
  await page.goto("/copilot");
  await page.getByTestId("copilot-input").fill("Which stocks should I sell to use margin for selling puts?");
  await page.getByTestId("copilot-send").click();
  await expect(page.getByRole("button", { name: "Calculate candidates" })).toBeDisabled();
  await page.getByLabel("Comparison goal", { exact: true }).selectOption("reduce_margin");
  await page.getByLabel("Reduction amount (USD)").fill("500");
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Calculate candidates" }).click();
  await expect(page.getByRole("region", { name: "Change comparison" })).toContainText("$4,500.00");
  await expect(page.getByTestId("copilot-input")).toHaveCount(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole("region", { name: "Candidate comparison", exact: true }).screenshot({ path: test.info().outputPath("candidate-comparison.png") });
  await page.reload();
  expect(starts).toBe(1);
  await page.getByRole("button", { name: "Retrieve original run" }).click();
  await expect(page.getByRole("region", { name: "Change comparison" })).toBeVisible();
  expect(starts).toBe(1);
});
