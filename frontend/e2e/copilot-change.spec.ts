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
    data: null, error: { code: "option_comparison_unavailable", message: "This book contains an unconfirmed option direction. No positions were removed or treated as zero risk." }, meta: { request_id: "test" },
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

test("mixed option book separates account stress from expiry boundaries in the same window", async ({ page }) => {
  const mixedSide = { ...side, annual_volatility: null, var_1d_95_usd: null, cvar_1d_95_usd: null,
    option_assets: 1288, option_liabilities: 860 };
  await page.route("**/api/v1/copilot/compare-change", (route) => route.fulfill({ json: { data: {
    result_id: "44444444-4444-4444-8444-444444444444", portfolio_id: book, computed_at: "2026-09-06T12:00:00Z",
    snapshot_digest: "mixed-fixture", methodology_version: "reduce-mixed-v1", price_as_of: "2026-09-04", history_start: "2026-01-01", observations: 100,
    assumptions: route.request().postDataJSON(), sources: { SGOV: "fixture", GOOGL: "fixture" },
    baseline: mixedSide, candidate: mixedSide, limitations: ["No guarantee against a margin call."],
    risk_method: "mixed_instant_stress", option_quote_basis: "Delayed quotes; timestamps unavailable",
    scenarios: [{ label: "Equity sell-off", shocks: { SGOV: -0.01, GOOGL: -0.2 }, iv_shift: 0.1, horizon_days: 0,
      baseline_pnl: -300, candidate_pnl: -290, baseline_equity: 7700, candidate_equity: 7710 }],
    option_groups: [{ underlying: "GOOGL", expiry: "2027-01-15", name: "Bull call spread", leg_count: 2,
      mark_basis_max_loss: 428, mark_basis_max_gain: 1572 }],
  }, error: null, meta: { request_id: "test" } } }));
  await page.goto("/copilot");
  await page.getByRole("button", { name: "Test a change", exact: true }).click();
  await page.getByLabel("Held ticker").fill("SGOV");
  await page.getByLabel("Amount to reduce (USD)").fill("1000");
  await page.getByRole("button", { name: "Compare assumptions" }).click();
  await expect(page.getByRole("region", { name: "Full-account stress scenarios" })).toContainText("$7,710");
  await expect(page.locator("dd > span").filter({ hasText: "Unavailable for mixed account" })).toHaveCount(6);
  await page.getByText("Unchanged option groups · expiry boundaries").click();
  await expect(page.getByText(/Max loss: \$428/)).toBeVisible();
  await expect(page.getByText(/Unbounded in option-only expiry model/)).toHaveCount(0);
  await expect(page.getByTestId("copilot-input")).toHaveCount(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.getByRole("region", { name: "Change comparison" }).screenshot({ path: test.info().outputPath("mixed-comparison.png") });
});

test("explicit historical verification survives reload without fetching a new comparison", async ({ page }) => {
  let comparisons = 0, verifications = 0;
  const receipt = { record: "opaque signed fixture", signature: "a".repeat(64) };
  const result = {
    result_id: "44444444-4444-4444-8444-444444444444", portfolio_id: book, computed_at: "2026-09-06T12:00:00Z",
    snapshot_digest: "fixture", methodology_version: "reduce-close-v1", price_as_of: "2026-09-04", history_start: "2026-01-01", observations: 100,
    assumptions: { expected_portfolio_id: book, ticker: "SGOV", amount: 1000, proceeds: "cash" }, sources: { SGOV: "fixture" },
    baseline: side, candidate: { ...side, cash: 2000 }, limitations: ["Not a saved plan."],
  };
  await page.route("**/api/v1/copilot/compare-change", (route) => { comparisons++; return route.fulfill({ json: {
    data: { ...result, replay_receipt: receipt }, error: null, meta: { request_id: "t" },
  } }); });
  await page.route("**/api/v1/copilot/compare-change/*/verify", (route) => {
    verifications++;
    expect(route.request().postDataJSON()).toEqual({ expected_portfolio_id: book, receipt: { ...receipt, save_available: false } });
    return route.fulfill({ json: { data: { result, verified_at: "2026-09-06T13:00:00Z", inputs_match_now: false,
      snapshot_age_seconds: 3600, recent_capture: false, notice: "Historical calculation reproduced; nothing saved." }, error: null, meta: { request_id: "v" } } });
  });
  await page.goto("/copilot");
  await page.getByRole("button", { name: "Test a change", exact: true }).click();
  await page.getByLabel("Held ticker").fill("SGOV");
  await page.getByLabel("Amount to reduce (USD)").fill("1000");
  await page.getByRole("button", { name: "Compare assumptions" }).click();
  await expect(page.getByRole("button", { name: "Verify captured calculation", exact: true })).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "Verify captured calculation", exact: true }).click();
  await expect(page.getByText(/Original calculation reproduced/)).toBeVisible();
  await expect(page.getByText(/Account inputs have changed/)).toBeVisible();
  await expect(page.getByText(/older than 15 minutes/)).toBeVisible();
  expect(comparisons).toBe(1); expect(verifications).toBe(1);
  await expect(page.getByTestId("copilot-input")).toHaveCount(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("explicit draft confirmation stays in one window and reload does not save twice", async ({ page }) => {
  let saves = 0;
  const receipt = { record: "signed fixture", signature: "a".repeat(64), save_available: true };
  const result = {
    result_id: "44444444-4444-4444-8444-444444444444", portfolio_id: book, computed_at: "2026-09-06T12:00:00Z",
    snapshot_digest: "fixture", methodology_version: "reduce-close-v1", price_as_of: "2026-09-04", history_start: "2026-01-01", observations: 100,
    assumptions: { expected_portfolio_id: book, ticker: "SGOV", amount: 1000, proceeds: "cash" },
    sources: { SGOV: "fixture" }, baseline: side, candidate: { ...side, cash: 2000, largest_position_weight: 9000 / 13000 }, limitations: ["Historical assumption, not an order."],
  };
  const saved = { result, plan_id: result.result_id, result_id: result.result_id, portfolio_id: book, confirmed_at: "2026-09-06T12:01:00Z", notice: "No holdings changed." };
  await page.route("**/api/v1/copilot/compare-change", route => route.fulfill({ json: { data: { ...result, replay_receipt: receipt }, error: null, meta: { request_id: "capture" } } }));
  await page.route("**/api/v1/copilot/compare-change/*/confirm", route => {
    saves++;
    expect(route.request().postDataJSON()).toEqual({ expected_portfolio_id: book, receipt, confirmed: true });
    return route.fulfill({ json: { data: saved, error: null, meta: { request_id: "confirm" } } });
  });
  await page.route("**/api/v1/copilot/compare-change/*/saved?*", route => route.fulfill({ json: { data: saved, error: null, meta: { request_id: "saved" } } }));
  await page.goto("/copilot");
  await page.getByRole("button", { name: "Test a change", exact: true }).click();
  await page.getByLabel("Held ticker").fill("SGOV");
  await page.getByLabel("Amount to reduce (USD)").fill("1000");
  await page.getByRole("button", { name: "Compare assumptions" }).click();
  await page.getByRole("button", { name: "Save as draft plan" }).click();
  await expect(page.getByRole("button", { name: "Confirm and save draft" })).toBeDisabled();
  expect(saves).toBe(0);
  await page.getByRole("checkbox", { name: /I confirm saving/ }).check();
  await page.getByRole("button", { name: "Confirm and save draft" }).click();
  await expect(page.getByText(/Draft saved/)).toBeVisible();
  await expect(page.getByRole("link", { name: "Open saved risk plans" })).toHaveAttribute("href", "/analyze?view=plan");
  await page.reload();
  await expect(page.getByText(/This tab remembers a saved plan/)).toBeVisible();
  expect(saves).toBe(1);
  await page.getByRole("button", { name: "Check saved record" }).click();
  await expect(page.getByText(/Draft saved/)).toBeVisible();
  expect(saves).toBe(1);
  await expect(page.getByTestId("copilot-input")).toHaveCount(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  // Capture the confirmation itself, not a tall element stitched through the
  // existing sticky header/composer (which produces misleading screenshots).
  await page.getByRole("status").filter({ hasText: "Draft saved" }).screenshot({ path: test.info().outputPath("confirmed-comparison.png") });
});
