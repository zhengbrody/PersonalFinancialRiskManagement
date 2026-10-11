import type { Page } from "@playwright/test";
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

// ---------------------------------------------------------------------------
// Outcome truthfulness and capability-boundary paths, plus compact viewports.
// ---------------------------------------------------------------------------
const fixture = riskFixture;
const book = fixture.result.portfolio_id;
const signed = { ...fixture.result, receipt: { record: "synthetic funding receipt", signature: "a".repeat(64), save_available: true } };
const saved = { plan_id: signed.result_id, portfolio_id: book, confirmed_at: signed.computed_at, result: fixture.result };
const rejection = (status: number, code: string, message: string) => ({ status, json: { data: null, error: { code, message }, meta: { request_id: "fixture" } } });

/** Installs the fixture backend for the ask → candidates → funding flow; save handling is per test. */
async function installFundingBackend(page: Page) {
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
    if (route.request().method() !== "POST") return route.fulfill({ json: envelope({ runs: [], untrusted_records: 0, dispatched: 0, removed: 0 }) });
    const body = route.request().postDataJSON();
    return route.fulfill({ json: envelope({ id: body.id, portfolio_id: book, state: "completed", step: "done", attempts: 1, error_code: null,
      result: { snapshot_id: body.id, portfolio_id: book, computed_at: fixture.source.computed_at, task: body.task,
        baseline: fixture.source.baseline, candidates: [fixture.source], preferred_result_id: null,
        coverage: "evaluated", judgment: "Compare the funding consequences before deciding.", excluded: {}, limitations: [] } }) });
  });
}

/** Ask → confirm constraints → candidates → open the funding form and fill every Put assumption. */
async function reachFundingForm(page: Page, { risk = true } = {}) {
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
  if (risk) {
    await page.getByLabel("Include explicit account-wide expiry price scenarios").check();
    await page.getByLabel("Scenario 1 name", { exact: true }).fill("Explicit downside");
    await page.getByLabel("Scenario 1 price 1", { exact: true }).fill("80");
    await page.getByLabel("Scenario 1 price 2", { exact: true }).fill("50");
    await page.getByLabel("Annual borrowing rate (%)", { exact: true }).fill("8");
  }
  await page.getByLabel("I confirm this reduction, protected holdings and option assumptions.").check();
  await page.getByLabel("Recorded cash is gross settled USD cash; listed put collateral and other cash holds must still be reserved.").check();
  await page.getByLabel("This is a standard, unadjusted 100-share physically settled USD equity put.").check();
}

const noOverflow = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);

test("an unknown save outcome is shown as uncertain, never as saved, and the identical receipt is retried", async ({ page }) => {
  await installFundingBackend(page);
  await page.route("**/api/v1/copilot/funding-scenarios", route => route.fulfill({ json: envelope(signed) }));
  const bodies: string[] = [];
  await page.route("**/api/v1/copilot/funding-plans/*/confirm", route => {
    bodies.push(route.request().postData() ?? "");
    if (bodies.length === 1) return route.fulfill(rejection(503, "funding_save_unconfirmed", "Saving was not confirmed. Retry the same result."));
    return route.fulfill({ json: envelope(saved) });
  });
  await reachFundingForm(page);
  await page.getByRole("button", { name: "Compare funding alternatives" }).click();
  await expect(page.getByRole("heading", { name: "Keep unchanged", exact: true }).first()).toBeVisible();
  await page.getByLabel("Save these original funding assumptions as a draft RiskPlan. This does not execute a trade.").check();
  await page.getByRole("button", { name: "Confirm save funding plan" }).click();
  await expect(page.getByRole("status").filter({ hasText: /Save status is unconfirmed/ })).toBeVisible();
  await expect(page.getByText("Verified original funding plan. No holdings or orders changed.")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Review funding assumptions" })).toHaveCount(0);
  // Consent survives an uncertain outcome so the SAME result can be retried without re-affirming a different one.
  await page.getByRole("button", { name: "Confirm save funding plan" }).click();
  await expect(page.getByText("Verified original funding plan. No holdings or orders changed.")).toBeVisible();
  expect(bodies).toHaveLength(2);
  expect(bodies[0]).toBe(bodies[1]);
});

test("a pre-commit rejection of the save is definite and carries the server's reason", async ({ page }) => {
  await installFundingBackend(page);
  await page.route("**/api/v1/copilot/funding-scenarios", route => route.fulfill({ json: envelope(signed) }));
  await page.route("**/api/v1/copilot/funding-plans/*/confirm", route => route.fulfill(rejection(409, "funding_plan_expired", "Capture new scenarios before saving.")));
  await reachFundingForm(page);
  await page.getByRole("button", { name: "Compare funding alternatives" }).click();
  await page.getByLabel("Save these original funding assumptions as a draft RiskPlan. This does not execute a trade.").check();
  await page.getByRole("button", { name: "Confirm save funding plan" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Capture new scenarios before saving." })).toBeVisible();
  await expect(page.getByText(/unconfirmed|Verified original funding plan/)).toHaveCount(0);
});

test("an unsupported option book is rejected explicitly, not rendered as an empty comparison", async ({ page }) => {
  await installFundingBackend(page);
  await page.route("**/api/v1/copilot/funding-scenarios", route => route.fulfill(rejection(422, "option_comparison_unavailable",
    "This book holds a call spread on the sale underlying. Only standard short Puts sharing one expiry are supported; no legs were dropped.")));
  await reachFundingForm(page);
  await page.getByRole("button", { name: "Compare funding alternatives" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Only standard short Puts sharing one expiry are supported" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Funding alternatives" })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Saved funding plan" })).toHaveCount(0);
  // The form is still there for a corrected assumption; the conversation was not replaced.
  await expect(page.getByRole("button", { name: "Compare funding alternatives" })).toBeEnabled();
  await expect(page.getByTestId("copilot-input")).toHaveCount(1);
});

test("a historical read that finds no plan does not leave a card claiming one", async ({ page }) => {
  await installFundingBackend(page);
  let reads = 0;
  await page.route("**/api/v1/copilot/funding-plans/*?expected_portfolio_id=*", route => {
    reads++;
    return route.fulfill(reads === 1 ? { json: envelope(saved) } : rejection(404, "funding_plan_missing", "Saved funding plan not found."));
  });
  await page.goto(`/copilot?funding_plan=${signed.result_id}`);
  await expect(page.getByRole("button", { name: "Funding portfolio", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Retrieve saved funding plan" }).click();
  await expect(page.getByText("Verified original funding plan. No holdings or orders changed.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Review funding assumptions" })).toBeVisible();
  await page.getByRole("button", { name: "Retrieve saved funding plan" }).click();
  await expect(page.getByRole("status").filter({ hasText: /No saved funding plan exists/ })).toBeVisible();
  await expect(page.getByRole("button", { name: "Review funding assumptions" })).toHaveCount(0);
  await expect(page.getByText(/^Saved 20/)).toHaveCount(0);
});

// Compact viewports: a 360px phone and a 740×360 landscape phone. Every
// confirm/save control must pass Playwright's actionability check (visible,
// stable, enabled, receives pointer events) where the user would tap it — a
// trial click proves the fixed bottom nav and sticky bars do not intercept it —
// and the document must never scroll horizontally.
for (const viewport of [{ width: 360, height: 740 }, { width: 740, height: 360 }]) {
  test.describe(`compact ${viewport.width}×${viewport.height}`, () => {
    test.use({ viewport, isMobile: true, hasTouch: true });

    test("composer, scenario forms, confirmation and save controls stay tap-actionable", async ({ page }) => {
      await installFundingBackend(page);
      await page.route("**/api/v1/copilot/funding-scenarios", route => route.fulfill({ json: envelope(signed) }));
      await page.route("**/api/v1/copilot/funding-plans/*/confirm", route => route.fulfill({ json: envelope(saved) }));
      await page.route("**/api/v1/copilot/funding-plans/*/review", route => route.fulfill({ json: envelope({
        plan_id: saved.plan_id, portfolio_id: book, reviewed_at: signed.computed_at, verdict: "assumptions_need_confirmation",
        changed_fields: [], reasons: ["Reconfirm the premium and settled cash."], live_quote_checked: false, holdings_changed_by_review: false,
      }) }));
      await page.goto("/copilot");
      await expect(page.getByRole("button", { name: "Funding portfolio", exact: true })).toBeVisible();
      expect(await noOverflow(page)).toBeLessThanOrEqual(0);
      // Composer: the Ask button must be tappable above the fixed bottom nav.
      await page.getByTestId("copilot-input").fill("Which holdings should I reduce to fund a put?");
      await page.getByTestId("copilot-send").click({ trial: true });
      await page.getByTestId("copilot-send").click();
      await page.getByLabel("Reduction amount (USD)").fill("6000");
      await page.getByLabel("I confirm this goal, amount and holdings to preserve for this comparison.").check();
      await page.getByRole("button", { name: "Calculate candidates" }).click({ trial: true });
      await page.getByRole("button", { name: "Calculate candidates" }).click();
      await expect(page.getByRole("region", { name: "Change comparison" })).toBeVisible();
      expect(await noOverflow(page)).toBeLessThanOrEqual(0);
      await page.getByText("Compare this reduction with Put funding").click();
      for (const [key, label] of Object.entries(putFieldLabels)) {
        await page.getByLabel(`Funding ${label}`, { exact: true }).fill(String(fixture.request.put[key as keyof typeof fixture.request.put]));
      }
      await page.getByLabel("Reduction fees (USD)").fill("10");
      // Expanded account-wide scenario form (table + per-row controls).
      await page.getByLabel("Include explicit account-wide expiry price scenarios").check();
      await page.getByLabel("Scenario 1 name", { exact: true }).fill("Explicit downside");
      await page.getByLabel("Scenario 1 price 1", { exact: true }).fill("80");
      await page.getByLabel("Scenario 1 price 2", { exact: true }).fill("50");
      await page.getByLabel("Annual borrowing rate (%)", { exact: true }).fill("8");
      await page.getByRole("button", { name: "Add ticker to scenario 1" }).click({ trial: true });
      await page.getByRole("button", { name: "Add price scenario" }).click({ trial: true });
      expect(await noOverflow(page)).toBeLessThanOrEqual(0);
      for (const label of [
        "I confirm this reduction, protected holdings and option assumptions.",
        "Recorded cash is gross settled USD cash; listed put collateral and other cash holds must still be reserved.",
        "This is a standard, unadjusted 100-share physically settled USD equity put.",
      ]) {
        await page.getByLabel(label).click({ trial: true });
        await page.getByLabel(label).check();
      }
      const compare = page.getByRole("button", { name: "Compare funding alternatives" });
      await compare.click({ trial: true });
      await compare.click();
      await expect(page.getByRole("region", { name: "Account-wide expiry scenarios" })).toBeVisible();
      expect(await noOverflow(page)).toBeLessThanOrEqual(0);
      const consent = page.getByLabel("Save these original funding assumptions as a draft RiskPlan. This does not execute a trade.");
      await consent.click({ trial: true });
      await consent.check();
      const save = page.getByRole("button", { name: "Confirm save funding plan" });
      await save.click({ trial: true });
      await save.click();
      await expect(page.getByText("Verified original funding plan. No holdings or orders changed.")).toBeVisible();
      const review = page.getByRole("button", { name: "Review funding assumptions" });
      await review.click({ trial: true });
      await review.click();
      await expect(page.getByText("Funding assumptions need confirmation")).toBeVisible();
      expect(await noOverflow(page)).toBeLessThanOrEqual(0);
      // After the long result, the composer must still be reachable and tappable.
      const input = page.getByTestId("copilot-input");
      await input.fill("Explain the funding gap");
      await page.getByTestId("copilot-send").click({ trial: true });
      await expect(page.getByTestId("copilot-input")).toHaveCount(1);
      await page.screenshot({ path: test.info().outputPath(`compact-${viewport.width}x${viewport.height}.png`) });
    });
  });
}
