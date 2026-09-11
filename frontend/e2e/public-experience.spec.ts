import { test, expect } from "./support/fixtures";

test("anonymous homepage ships product copy and FAQ without JavaScript", async ({ request }) => {
  const response = await request.get("/");
  expect(response.status()).toBe(200);
  const html = await response.text();
  expect(html).toContain("Understand your risk");
  expect(html).toContain("ILLUSTRATIVE SAMPLE");
  expect(html).toContain('"@type":"FAQPage"');
});

test("sample comparison works with keyboard, reset, disclosures and safe onboarding", async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Understand your risk before your next move.");
  await page.getByRole("link", { name: /Try a sample portfolio/ }).click();
  const demo = page.getByRole("region", { name: "Interactive sample portfolio" });
  await expect(demo.getByText("$21,000", { exact: true })).toBeVisible();
  await demo.getByRole("radio", { name: "Repay margin" }).check();
  await expect(demo.getByRole("row", { name: /Margin loan/ })).toContainText("$10,000");
  await demo.getByRole("slider").focus();
  await page.keyboard.press("End");
  await expect(demo.getByRole("slider")).toHaveValue("50");
  await expect(demo.getByText("$18,000", { exact: true })).toBeVisible();
  await demo.getByRole("combobox").selectOption("-30");
  await expect(demo.getByText("$27,000", { exact: true })).toBeVisible();
  await demo.getByText("How this sample is calculated", { exact: true }).click();
  await expect(demo.getByText(/not VaR, maximum possible loss/)).toBeVisible();
  await demo.getByRole("button", { name: /Reset demo/ }).click();
  await expect(demo.getByRole("radio", { name: "Keep as cash" })).toBeChecked();
  await expect(demo.getByText("$21,000", { exact: true })).toBeVisible();
  await demo.getByText("How this sample is calculated", { exact: true }).click();
  await page.evaluate(() => { document.documentElement.classList.remove("dark"); window.scrollTo(0, 0); });
  await page.screenshot({ path: testInfo.outputPath("home-light.png"), fullPage: true, animations: "disabled", scale: "css" });
  await page.screenshot({ path: testInfo.outputPath("home-first-screen.png"), animations: "disabled", scale: "css" });
  await page.evaluate(() => document.documentElement.classList.add("dark"));
  await page.screenshot({ path: testInfo.outputPath("home-dark.png"), fullPage: true, animations: "disabled", scale: "css" });
  await page.getByRole("link", { name: "Analyze my portfolio" }).first().click();
  await expect(page).toHaveURL(/signup\?next=%2Fportfolios%2Fnew/);
  await expect(page.getByRole("heading", { name: "Create your account" })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("signup.png"), fullPage: true });
  expect(errors).toEqual([]);
});

test("public pages keep readable layout and unique titles", async ({ page }, testInfo) => {
  for (const path of ["/", "/product", "/demo-risk-check", "/learn", "/portfolio-risk-management", "/login"]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
    const overflow = await page.evaluate(() => [...document.querySelectorAll("h1, button, input, select, th, td")]
      .filter(el => el.getClientRects().length)
      .filter(el => { const r = el.getBoundingClientRect(); return r.left < -1 || r.right > innerWidth + 1; })
      .map(el => el.textContent));
    expect(overflow, path).toEqual([]);
    await expect(page.locator('link[rel="canonical"]')).toHaveAttribute("href", new RegExp(`${path === "/" ? "/?" : path}$`));
  }
  await page.screenshot({ path: testInfo.outputPath("login.png"), fullPage: true });
});
