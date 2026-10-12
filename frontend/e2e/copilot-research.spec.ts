import { test, expect } from "./support/fixtures";
import { seedSession, E2E_USER } from "./support/auth";
import research from "../src/test-fixtures/copilot-research.json";
import hypotheses from "../src/test-fixtures/copilot-research-hypotheses.json";

test("research stays in the Copilot with dated sources and counterpoints", async ({ page }) => {
  await seedSession(page);
  await page.route("**/api/v1/copilot/ask", route => route.fulfill({ json: {
    data: { intent: "ticker_research", tickers: ["AAPL"], answer_markdown: "Check the business assumptions.",
      evidence: [], data_only: true, research_context: [research] },
    error: null, meta: { request_id: "synthetic-research" },
  } }));
  await page.goto("/copilot");
  await page.getByTestId("copilot-input").fill("Research AAPL");
  await page.getByTestId("copilot-send").click();
  await page.getByText("AAPL · available").click();
  await expect(page.getByText("20.00× · available")).toBeVisible();
  await expect(page.getByText(/Past growth can reflect/)).toBeVisible();
  await expect(page.getByText(/Author unknown · Conflicts not disclosed/)).toBeVisible();
  await expect(page.getByTestId("copilot-input")).toHaveCount(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole("region", { name: "Research context", exact: true }).screenshot({ path: test.info().outputPath("research-context.png") });
});

const book = "33333333-3333-4333-8333-333333333333";
const side = { gross_assets: 13000, net_equity: 8000, cash: 1000, margin: 5000, leverage: 1.625, largest_position_weight: 0.77, annual_volatility: 0.2, var_1d_95_usd: 100, cvar_1d_95_usd: 180 };

test("a research hypothesis becomes a user-confirmed price assumption in the same window", async ({ page }) => {
  await seedSession(page);
  await page.route("**/api/v1/portfolios/me", (route) => route.fulfill({ json: {
    data: { user_id: E2E_USER.id, email: E2E_USER.email, portfolios: [{
      id: book, user_id: E2E_USER.id, name: "Comparison portfolio", holdings: { AAPL: { shares: 10 }, SPY: { shares: 10 } },
      is_default: true, margin_loan: 0, contributed_capital: 7500, cash_balance: 1000, created_at: null, updated_at: null,
    }] }, error: null, meta: { request_id: "fixture" },
  } }));
  await page.route("**/api/v1/copilot/ask", route => route.fulfill({ json: {
    data: { intent: "ticker_research", tickers: ["AAPL"], answer_markdown: "Check the business assumptions.",
      evidence: [], data_only: true, research_context: [hypotheses] },
    error: null, meta: { request_id: "synthetic-hypotheses" },
  } }));
  const bodies: unknown[] = [];
  await page.route("**/api/v1/copilot/compare-change", async (route) => {
    const assumptions = route.request().postDataJSON();
    bodies.push(assumptions);
    await route.fulfill({ json: { data: {
      result_id: "44444444-4444-4444-8444-444444444444", portfolio_id: book, computed_at: "2026-09-06T12:00:00Z",
      snapshot_digest: "fixture", methodology_version: "reduce-close-v1", price_as_of: "2026-09-04", history_start: "2026-01-01", observations: 100,
      assumptions, sources: { AAPL: "fixture", SPY: "fixture" }, baseline: side, candidate: { ...side, cash: 1500, gross_assets: 13000 },
      limitations: [],
      hypothesis_scenario: { hypothesis_id: "AAPL:h0", subject: "AAPL", price_change_pct: -20, basis: "user_assumption", status: "computed", reason: null,
        subject_value_baseline: 2000, subject_value_candidate: 1500, baseline_pnl: -400, candidate_pnl: -300, baseline_equity: 7600, candidate_equity: 7700 },
    }, error: null, meta: { request_id: "test" } } });
  });
  await page.goto("/copilot");
  await page.getByText("Comparison portfolio").first().waitFor();
  await page.getByTestId("copilot-input").fill("I think AAPL net margin is above 15%");
  await page.getByTestId("copilot-send").click();
  await page.getByText("AAPL · available").click();
  const card = page.getByRole("article", { name: "Hypothesis AAPL:h0" });
  await expect(card.getByText("Your assumption")).toBeVisible();
  await expect(card.getByText("Model inference (not evidence)")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await card.screenshot({ path: test.info().outputPath("hypothesis-card.png") });
  await card.getByRole("button", { name: "Test in account comparison" }).click();
  await expect(page.getByLabel("Held ticker")).toHaveValue("AAPL");
  await page.getByLabel("Amount to reduce (USD)").fill("500");
  await page.getByLabel(/Your assumed AAPL price change/).fill("-20");
  await page.getByRole("button", { name: "Compare assumptions" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Confirm that the price change is your own assumption" })).toBeVisible();
  expect(bodies).toHaveLength(0);
  await page.getByLabel(/This price change is my own assumption/).check();
  await page.getByRole("button", { name: "Compare assumptions" }).click();
  const scenario = page.getByRole("region", { name: "Research assumption scenario" });
  await expect(scenario).toContainText("P&L -$300.00");
  expect(bodies).toEqual([{ expected_portfolio_id: book, ticker: "AAPL", amount: 500, proceeds: "cash",
    hypothesis: { hypothesis_id: "AAPL:h0", subject: "AAPL", price_change_pct: -20, basis: "user_assumption", user_confirmed: true } }]);
  expect(JSON.stringify(bodies)).not.toContain("net margin");
  await expect(page.getByTestId("copilot-input")).toHaveCount(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await scenario.screenshot({ path: test.info().outputPath("hypothesis-scenario.png") });
});
