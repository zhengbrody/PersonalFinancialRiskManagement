import { test, expect } from "./support/fixtures";
import { seedSession, E2E_USER } from "./support/auth";
import legacyFixture from "../src/test-fixtures/copilot-funding-candidate.json";
import riskFixture from "../src/test-fixtures/copilot-funding-risk.json";
import { putFieldLabels } from "../src/lib/put-fields";

const envelope = (data: unknown) => ({ data, error: null, meta: { request_id: "fixture" } });
for (const includeRisk of [false, true]) {
const fixture = includeRisk ? riskFixture : legacyFixture;
const book = fixture.result.portfolio_id;
const signed = { ...fixture.result, receipt: { record: "synthetic funding receipt", signature: "a".repeat(64), save_available: true } };
const saved = { plan_id: signed.result_id, portfolio_id: book, confirmed_at: signed.computed_at, result: fixture.result };

test(`funding comparison, signed save and account review stay in one Copilot (${includeRisk ? "account risk" : "funding only"})`, async ({ page }, testInfo) => {
  await seedSession(page);
  await page.route("**/api/v1/portfolios/me", route => route.fulfill({ json: envelope({
    user_id: E2E_USER.id, email: E2E_USER.email, portfolios: [{ id: book, user_id: E2E_USER.id,
      name: "Funding portfolio", holdings: { QQQ: { shares: 100 }, SPY: { shares: 10 } }, is_default: true,
      cash_balance: 1000, margin_loan: 5000, contributed_capital: 8000, created_at: null, updated_at: null }],
  }) }));
  await page.route("**/api/v1/copilot/ask", route => route.fulfill({ json: envelope({
    intent: "action_plan", tickers: [], answer_markdown: "Confirm a reduction and compare cash, debt and assignment obligations.", evidence: [], data_only: true,
    decision_support: { version: 1, task: { kind: "candidate_request", goal: null, missing_inputs: ["budget"], confirmed_constraints: {} },
      coverage: "insufficient_data", methods: [], limitations: [], save_available: false,
      candidate_comparison_available: true, funding_scenarios_available: true },
  }) }));
  await page.route("**/api/v1/copilot/decision-runs", route => {
    if (route.request().method() !== "POST") return route.fulfill({ json: envelope({ runs: [], untrusted_records: 0 }) });
    const body = route.request().postDataJSON();
    return route.fulfill({ json: envelope({ id: body.id, portfolio_id: book, state: "completed", step: "done", attempts: 1, error_code: null,
      result: { snapshot_id: body.id, portfolio_id: book, computed_at: fixture.source.computed_at, task: body.task,
        baseline: fixture.source.baseline, candidates: [fixture.source], preferred_result_id: null,
        coverage: "evaluated", judgment: "Compare the funding consequences before deciding.", excluded: {}, limitations: [] } }) });
  });
  await page.route("**/api/v1/copilot/funding-scenarios", route => {
    expect(route.request().postDataJSON()).toEqual({ ...fixture.request, risk: includeRisk ? riskFixture.request.risk : null });
    return route.fulfill({ json: envelope(signed) });
  });
  await page.route("**/api/v1/copilot/funding-plans/*/confirm", route => {
    expect(route.request().postDataJSON().confirmed).toBe(true);
    return route.fulfill({ json: envelope(saved) });
  });
  await page.route("**/api/v1/copilot/funding-plans/*?expected_portfolio_id=*", route => route.fulfill({ json: envelope(saved) }));
  await page.route("**/api/v1/copilot/funding-plans/*/review", route => route.fulfill({ json: envelope({
    plan_id: saved.plan_id, portfolio_id: book, reviewed_at: signed.computed_at, verdict: "requires_recalculation",
    changed_fields: ["cash_balance"], reasons: ["Recorded cash changed; recalculate before using this plan."],
    live_quote_checked: false, holdings_changed_by_review: false,
  }) }));
  await page.goto("/copilot");
  await expect(page.getByRole("button", { name: "Funding portfolio", exact: true })).toBeVisible();
  await page.getByTestId("copilot-input").fill("Which holdings should I reduce to fund a put?");
  await page.getByTestId("copilot-send").click();
  await page.getByLabel("Reduction amount (USD)").fill("6000");
  await page.getByLabel("I confirm this goal, amount and holdings to preserve for this comparison.").check();
  await page.getByRole("button", { name: "Calculate candidates" }).click();
  await page.getByText("Compare this reduction with Put funding").click();
  for (const [key, label] of Object.entries(putFieldLabels)) {
    await page.getByLabel(`Funding ${label}`, { exact: true }).fill(String(fixture.request.put[key as keyof typeof fixture.request.put]));
  }
  await page.getByLabel("Reduction fees (USD)").fill("10");
  if (includeRisk) {
    await page.getByLabel("Include explicit account-wide expiry price scenarios").check();
    await expect(page.getByRole("button", { name: "Compare funding alternatives" })).toBeDisabled();
    await page.getByLabel("Scenario 1 name", { exact: true }).fill("Explicit downside");
    await page.getByLabel("Scenario 1 price 1", { exact: true }).fill("80");
    await page.getByLabel("Scenario 1 price 2", { exact: true }).fill("50");
    await page.getByLabel("Annual borrowing rate (%)", { exact: true }).fill("8");
  }
  await page.getByLabel("I confirm this reduction, protected holdings and option assumptions.").check();
  await page.getByLabel("Recorded cash is gross settled USD cash; listed put collateral and other cash holds must still be reserved.").check();
  await page.getByLabel("This is a standard, unadjusted 100-share physically settled USD equity put.").check();
  await page.getByRole("button", { name: "Compare funding alternatives" }).click();
  await expect(page.getByRole("heading", { name: "Keep unchanged", exact: true }).first()).toBeVisible();
  if (includeRisk) await expect(page.getByRole("region", { name: "Account-wide expiry scenarios" })).toBeVisible();
  await expect(page.getByText("Financing rules and account permissions are required before judging feasibility.")).toBeVisible();
  await expect(page.getByText("$8,811.00", { exact: true }).first()).toBeVisible();
  await expect(page.getByTestId("copilot-input")).toHaveCount(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByLabel("Save these original funding assumptions as a draft RiskPlan. This does not execute a trade.").check();
  await page.getByRole("button", { name: "Confirm save funding plan" }).click();
  await expect(page.getByText("Verified original funding plan. No holdings or orders changed.")).toBeVisible();
  await page.getByRole("button", { name: "Review funding assumptions" }).click();
  await expect(page.getByText("Recalculate funding scenario")).toBeVisible();
  await page.getByRole("region", { name: "Funding alternatives" }).screenshot({ path: testInfo.outputPath("funding-alternatives.png") });
  await page.goto(`/copilot?funding_plan=${signed.result_id}`);
  await expect(page.getByRole("button", { name: "Funding portfolio", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Retrieve saved funding plan" }).click();
  await expect(page.getByText("Verified original funding plan. No holdings or orders changed.")).toBeVisible();
});

}
