import { test, expect } from "./support/fixtures";
import { seedSession, E2E_USER } from "./support/auth";
import fixture from "../src/test-fixtures/plan-history.json";

const envelope = (data: unknown) => ({ data, error: null, meta: { request_id: "fixture" } });
const portfolio = fixture.page.plans[0].portfolio_id;

test("saved plans load from the server in a fresh session and review in the same window", async ({ page }) => {
  // Fresh browser context: nothing in sessionStorage/localStorage except the auth session.
  await seedSession(page);
  await page.route("**/api/v1/portfolios/me", route => route.fulfill({ json: envelope({
    user_id: E2E_USER.id, email: E2E_USER.email, portfolios: [{
      id: portfolio, user_id: E2E_USER.id, name: "History portfolio", holdings: { SGOV: { shares: 100 }, SPY: { shares: 20 } },
      is_default: true, cash_balance: 500, margin_loan: 5000, contributed_capital: 7500, created_at: null, updated_at: null,
    }],
  }) }));
  const requests: string[] = [];
  await page.route("**/api/v1/copilot/saved-plans?*", route => { requests.push(route.request().url()); return route.fulfill({ json: envelope(fixture.page) }); });
  await page.route(`**/api/v1/copilot/saved-plans/${fixture.page.plans[0].plan_id}?*`, route => route.fulfill({ json: envelope(fixture.detail) }));
  await page.route("**/api/v1/copilot/saved-plans/*/metric-review", route => {
    expect(route.request().postDataJSON()).toEqual({ expected_portfolio_id: portfolio });
    return route.fulfill({ json: envelope(fixture.review) });
  });
  await page.goto("/copilot");
  await expect(page.getByRole("button", { name: "History portfolio", exact: true })).toBeVisible();
  await page.getByText("Saved plans", { exact: true }).click();
  await page.getByRole("button", { name: "Load saved plans" }).click();
  await expect(page.getByText(/Hypothetical reduction of SPY/)).toBeVisible();
  expect(requests[0]).toContain(`expected_portfolio_id=${portfolio}`);
  // The plan came from the server: no client storage carries it (no receipt, no id).
  const stored = await page.evaluate(() => JSON.stringify([{ ...sessionStorage }, { ...localStorage }]));
  expect(stored).not.toContain(fixture.page.plans[0].plan_id);
  await page.getByRole("button", { name: "Open original evidence" }).click();
  await expect(page.getByLabel("Original evidence")).toBeVisible();
  await page.getByRole("button", { name: "Run review" }).click();
  const review = page.getByLabel("Plan review");
  await expect(review.getByText("Same method: changes since saving")).toBeVisible();
  await expect(review.getByText("+$800")).toBeVisible();
  await expect(page.getByTestId("copilot-input")).toHaveCount(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: test.info().outputPath("plan-history.png"), fullPage: true });
});
