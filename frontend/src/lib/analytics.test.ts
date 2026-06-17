import { describe, expect, it } from "vitest";
import { redactProps, sanitizePageviewUrl } from "./analytics";

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

describe("redactProps (defense-in-depth)", () => {
  it("drops any investment-content key, keeps aggregate/funnel keys", () => {
    const out = redactProps({
      // sensitive → must be dropped
      ticker: "NVDA",
      symbol: "AAPL",
      holdings: 12,
      prompt: "should I sell?",
      portfolio_id: "p-1",
      dollar_value: 50000,
      net_equity: 120000,
      strike: 150,
      // safe → must be kept
      kind: "portfolio",
      shock_pct: -0.2,
      intent: "margin_risk",
      tab: "valuation",
      source: "score",
      overall_score: 712,
    });
    expect(out).toEqual({
      kind: "portfolio",
      shock_pct: -0.2,
      intent: "margin_risk",
      tab: "valuation",
      source: "score",
      overall_score: 712,
    });
  });

  it("passes undefined through and never throws", () => {
    expect(redactProps(undefined)).toBeUndefined();
    expect(redactProps({})).toEqual({});
  });
});
