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

describe("identify privacy (Privacy Policy: UUID only, no email)", () => {
  it("redactProps strips email and every deny-list person property", () => {
    const out = redactProps({
      email: "user@example.com",
      user_email: "user@example.com",
      ticker: "NVDA",
      portfolio_id: "p1",
      prompt: "should I sell?",
      amount_usd: 5000,
      plan: "free", // safe funnel prop survives
    });
    expect(out).toEqual({ plan: "free" });
    expect(JSON.stringify(out)).not.toContain("example.com");
  });
});
