import { test, expect } from "./support/fixtures";
import { seedSession } from "./support/auth";

const CHECK = {
  portfolio_id: "pf1",
  result_id: "fixture-check",
  methodology_version: "risk-check-v1",
  computed_at: "2026-09-05T12:00:00Z",
  price_history_as_of: "2026-09-04",
  status: "limited",
  summary:
    "Inspect downside, concentration and financing before making a change.",
  findings: [
    {
      key: "coverage",
      title: "Review model coverage",
      severity: "info",
      explanation:
        "Option expiry bounds and daily account losses answer different questions.",
    },
  ],
  metrics: [
    {
      key: "var",
      label: "A bad day: estimated loss threshold",
      value: 1250,
      unit: "usd",
      horizon: "1 trading day",
      basis: "Report net-equity basis",
      explanation: "Historical 95% VaR. Not a maximum loss.",
      source_field: "losses.var_1d_95.usd",
    },
    {
      key: "cvar",
      label: "When that bad day gets worse",
      value: 2100,
      unit: "usd",
      horizon: "1 trading day",
      basis: "Report net-equity basis",
      explanation: "Average loss in the modeled worst 5% of days.",
      source_field: "losses.cvar_1d_95.usd",
    },
    {
      key: "coverage",
      label: "Unavailable estimate",
      value: null,
      unit: "fraction",
      horizon: "Historical",
      basis: "Covered holdings",
      explanation: "Missing input is not zero risk.",
      source_field: "correlation.avg_pairwise",
    },
  ],
  strategies: [
    {
      underlying: "XYZ",
      expiry: "2027-01-15",
      name: "bull_call_spread",
      leg_count: 2,
      premium_basis: "entry",
      max_loss: 400,
      max_gain: 1600,
      loss_status: "bounded",
      gain_status: "bounded",
    },
  ],
  limitations: [
    "Account risk uses a delta approximation. Expiry bounds do not include early assignment.",
    "Historical risk is not your realized YTD return. Deposits are not investment gains.",
  ],
};

test.beforeEach(async ({ page }) => {
  await seedSession(page);
  await page.route("**/api/v1/risk/report_from_active", async (route) => {
    expect(route.request().postDataJSON()).toEqual({
      expected_portfolio_id: "pf1",
      include_copilot_check: true,
    });
    await route.fulfill({
      json: {
        data: { copilot_check: CHECK },
        error: null,
        meta: { request_id: "test" },
      },
    });
  });
});
test("check, inspect evidence and option bounds without leaving the conversation", async ({
  page,
}, info) => {
  await page.goto("/copilot");
  await expect(
    page.getByText("Working with My Portfolio", { exact: false }),
  ).toBeVisible();
  await expect(page.getByRole("textbox")).toHaveCount(1);
  await page
    .getByRole("button", { name: "Check my portfolio", exact: true })
    .click();
  await expect(page.getByText("Review model coverage")).toBeVisible();
  await page.getByRole("button", { name: "Understand the numbers" }).click();
  await expect(page.getByText("$1,250")).toBeVisible();
  await expect(page.getByText("Unavailable", { exact: true })).toBeVisible();
  await page
    .getByText("Your options — grouped expiry risk", { exact: true })
    .click();
  await expect(page.getByText("$400.00", { exact: true })).toBeVisible();
  await expect(page).toHaveURL(/\/copilot$/);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth - innerWidth,
    ),
  ).toBeLessThanOrEqual(1);
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);
  await page.screenshot({
    path: info.outputPath("copilot-check.png"),
    fullPage: true,
  });
  await page.screenshot({ path: info.outputPath("copilot-viewport.png") });
  const mobileNav = page.getByRole("navigation", {
    name: "Mobile primary navigation",
  });
  if (await mobileNav.isVisible()) {
    const submit = await page
      .getByRole("button", { name: "Ask", exact: true })
      .boundingBox();
    const nav = await mobileNav.boundingBox();
    expect(submit!.y + submit!.height).toBeLessThanOrEqual(nav!.y);
  }
  await page.reload();
  await expect(page.getByText("Review model coverage")).toBeVisible();
  await expect(page.getByRole("textbox")).toHaveCount(1);
});

test("query prefill is not automatically submitted", async ({ page }) => {
  let calls = 0;
  page.on("request", (request) => {
    if (request.url().includes("/copilot/ask")) calls++;
  });
  await page.goto("/copilot?q=Explain%20my%20risk");
  await expect(page.getByRole("textbox")).toHaveValue("Explain my risk");
  expect(calls).toBe(0);
});

test("old-portfolio response is refused in the same window", async ({
  page,
}) => {
  await page.route("**/api/v1/risk/report_from_active", (route) =>
    route.fulfill({
      json: {
        data: { copilot_check: { ...CHECK, portfolio_id: "other" } },
        error: null,
        meta: { request_id: "test" },
      },
    }),
  );
  await page.goto("/copilot");
  await expect(
    page.getByText("Working with My Portfolio", { exact: false }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Check my portfolio", exact: true })
    .click();
  await expect(page.getByText(/belongs to another portfolio/)).toBeVisible();
  await expect(page.getByText("Review model coverage")).toHaveCount(0);
});
