import { test, expect } from "./support/fixtures";
import { seedSession, E2E_USER } from "./support/auth";

const book = "33333333-3333-4333-8333-333333333333";
const id = "44444444-4444-4444-8444-444444444444";

test("recover a saved check after reload without starting another analysis", async ({ page }) => {
  await seedSession(page);
  await page.route("**/api/v1/portfolios/me", (route) => route.fulfill({ json: {
    data: { user_id: E2E_USER.id, email: E2E_USER.email, portfolios: [{
      id: book, user_id: E2E_USER.id, name: "Recovery portfolio", holdings: { SPY: { shares: 2 } },
      is_default: true, margin_loan: 0, contributed_capital: 1000, cash_balance: 100,
      created_at: null, updated_at: null,
    }] }, error: null, meta: { request_id: "fixture" },
  } }));
  await page.goto("/copilot");
  await expect(page.getByText("Working with Recovery portfolio", { exact: false })).toBeVisible();
  await page.evaluate(({ key, id }) => {
    sessionStorage.setItem(key, JSON.stringify([{
      id, runId: id, question: "Check my portfolio", kind: "check", status: "running",
    }]));
  }, { key: `mm:copilot:thread:v1:${E2E_USER.id}:${book}`, id });
  let gets = 0;
  await page.route(`**/api/v1/copilot/runs/${id}`, (route) => {
    expect(route.request().method()).toBe("GET");
    gets++;
    return route.fulfill({ json: { data: {
      id, portfolio_id: book, state: "completed",
      created_at: "2026-09-06T12:00:00Z", updated_at: "2026-09-06T12:00:01Z",
      expires_at: "2026-09-06T12:10:00Z", error_code: null,
      result: {
        portfolio_id: book, result_id: id, methodology_version: "risk-check-v1",
        computed_at: "2026-09-06T12:00:01Z", status: "limited", summary: "Recovered the original check.",
        price_history_as_of: null,
        findings: [], metrics: [], strategies: [], limitations: ["Original captured holdings; not current market prices."],
      },
    }, error: null, meta: { request_id: "fixture" } } });
  });
  const starts: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && /\/(copilot\/runs|risk\/report_from_active)$/.test(request.url())) starts.push(request.url());
  });
  await page.reload();
  await expect(page.getByRole("button", { name: "Retrieve saved result" })).toBeVisible();
  expect(gets).toBe(0);
  await page.getByRole("button", { name: "Retrieve saved result" }).click();
  await expect(page.getByText("Recovered the original check.")).toBeVisible();
  expect(gets).toBe(1);
  expect(starts).toEqual([]);
  await expect(page.getByRole("textbox")).toHaveCount(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
});
