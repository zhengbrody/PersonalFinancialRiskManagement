import { test, expect } from "./support/fixtures";
import { seedSession } from "./support/auth";
import research from "../src/test-fixtures/copilot-research.json";

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
