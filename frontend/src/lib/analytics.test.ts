import { describe, expect, it } from "vitest";
import { sanitizePageviewUrl } from "./analytics";

describe("sanitizePageviewUrl", () => {
  it("keeps only origin and pathname for absolute URLs", () => {
    expect(
      sanitizePageviewUrl(
        "https://mindmarket.app/portfolios?code=oauth-secret&ticker=NVDA#session",
      ),
    ).toBe("https://mindmarket.app/portfolios");
  });

  it("strips query and hash from relative-like fallback strings", () => {
    expect(sanitizePageviewUrl("/research?ticker=AAPL#top")).toBe("/research");
  });
});
