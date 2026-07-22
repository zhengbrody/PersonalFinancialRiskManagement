import { expect, test } from "./support/fixtures";

test.describe("protected journey handoff", () => {
  test("preserves an allowlisted Analyze stage across sign-in", async ({ page }) => {
    await page.goto("/analyze?view=stress&ticker=NVDA");

    await expect(page).toHaveURL(
      /\/login\?next=%2Fanalyze%3Fview%3Dstress$/,
    );
    await expect(page.getByRole("heading", { name: "Welcome back" })).toBeVisible();

    // The arbitrary ticker query is deliberately not carried over the auth
    // boundary; only the allowlisted, non-sensitive workflow stage survives.
    expect(page.url()).not.toContain("NVDA");
  });
});
