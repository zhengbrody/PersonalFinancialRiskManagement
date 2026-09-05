import { test, expect } from "./support/fixtures";
import { seedSession } from "./support/auth";

test.beforeEach(async ({ page }) => {
  await seedSession(page);
});

test("small phones and tablets retain usable navigation without overflow", async ({ page }) => {
  await page.goto("/analyze");
  await expect(page.getByTestId("analyze-overall-score")).toBeVisible();
  for (const width of [360, 390, 768, 1024]) {
    await page.setViewportSize({ width, height: 900 });
    const navigation = page.getByRole("navigation", { name: width < 1024 ? "Mobile primary navigation" : "Primary navigation", exact: true });
    await expect(navigation).toBeVisible();
    for (const tab of ["Overview", "Drivers", "Stress Test", "Action Plan", "History"]) {
      await expect(page.getByRole("tab", { name: tab, exact: true })).toBeVisible();
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
  }
});

test("primary navigation and guided stages stay connected", async ({
  page,
  isMobile,
}) => {
  await page.goto("/analyze?view=overview");
  const nav = page.getByRole("navigation", {
    name: isMobile ? "Mobile primary navigation" : "Primary navigation",
    exact: true,
  });
  await expect(
    nav.getByRole("link", { name: "Analyze", exact: true }),
  ).toHaveAttribute("aria-current", "page");
  await expect(
    page.getByRole("heading", { name: "Understand your starting point" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Explore risk drivers" }).click();
  await expect(page).toHaveURL(/view=drivers/);
  await page
    .getByRole("button", { name: "Test a scenario", exact: true })
    .click();
  await expect(page).toHaveURL(/view=stress/);
  await expect(
    page.getByText(/Simulation only · holdings unchanged/),
  ).toBeVisible();
  await page.goBack();
  await expect(
    page.getByRole("tab", { name: "Drivers", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
  await nav.getByRole("link", { name: "Holdings", exact: true }).click();
  await expect(page).toHaveURL(/\/portfolios$/);
  await expect(
    nav.getByRole("link", { name: "Holdings", exact: true }),
  ).toHaveAttribute("aria-current", "page");
});

for (const theme of ["light", "dark"]) {
  test(`workspace layouts in ${theme} mode`, async ({ page }, testInfo) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    for (const path of ["/", "/analyze", "/portfolios"]) {
      await page.goto(path);
      await expect(page.locator("main h1")).toBeVisible();
      if (path === "/")
        await expect(
          page.getByText("Do this next", { exact: true }),
        ).toBeVisible();
      if (path === "/analyze")
        await expect(page.getByTestId("analyze-overall-score")).toBeVisible();
      if (path === "/portfolios")
        await expect(
          page.getByRole("button", { name: "Risk report", exact: true }),
        ).toBeVisible();
      await expect(
        page.getByRole("button", { name: "My Portfolio", exact: true }),
      ).toBeVisible();
      await page.evaluate(
        (dark) => document.documentElement.classList.toggle("dark", dark),
        theme === "dark",
      );
      expect(
        await page.evaluate(
          () =>
            document.documentElement.scrollWidth -
            document.documentElement.clientWidth,
        ),
      ).toBeLessThanOrEqual(1);
      await page.screenshot({
        path: testInfo.outputPath(
          `${path === "/" ? "today" : path.slice(1)}-${theme}.png`,
        ),
        fullPage: true,
        animations: "disabled",
      });
    }
    expect(errors).toEqual([]);
  });
}

test("market context is an explicit optional disclosure", async ({ page }) => {
  await page.goto("/");
  const context = page
    .locator("details")
    .filter({ has: page.locator("summary", { hasText: "Market context" }) });
  await expect(context).toBeVisible();
  await expect(context).not.toHaveAttribute("open");
  await context.locator("summary").click();
  await expect(context).toHaveAttribute("open", "");
});

test("portfolio switcher and secondary actions work with the keyboard", async ({
  page,
}) => {
  await page.goto("/portfolios");
  await page.getByRole("button", { name: "My Portfolio", exact: true }).click();
  await expect(page.getByRole("option", { selected: true })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("listbox")).not.toBeVisible();
  await page.locator("summary", { hasText: "More actions" }).click();
  await expect(
    page.getByRole("button", { name: "Export My Portfolio as CSV" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Delete My Portfolio", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Delete forever" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Delete forever" }),
  ).not.toBeVisible();
});
