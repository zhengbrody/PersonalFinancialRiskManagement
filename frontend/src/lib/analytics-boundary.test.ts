/**
 * PostHog WIRE boundary — proves (per the Privacy Policy) that email and
 * every deny-listed property physically cannot reach posthog-js, i.e. never
 * leave the browser. posthog-js itself is mocked; we assert on exactly what
 * would have been transmitted.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

const capture = vi.fn();
const identify = vi.fn();
const init = vi.fn();
vi.mock("posthog-js", () => ({
  default: { init, capture, identify, reset: vi.fn() },
}));

describe("PostHog wire boundary (Privacy Policy)", () => {
  beforeEach(() => {
    vi.resetModules();
    init.mockClear();
    capture.mockClear();
    identify.mockClear();
    vi.stubEnv("NODE_ENV", "production"); // analytics only arms in production
  });

  it("identify transmits the Supabase UUID with scrubbed props only", async () => {
    const a = await import("./analytics");
    a.initAnalytics();
    a.identifyUser("00000000-0000-4000-8000-000000000001", {
      email: "user@example.com",
      ticker: "NVDA",
      portfolio_id: "p-1",
      plan: "free",
    });
    expect(identify).toHaveBeenCalledTimes(1);
    expect(identify).toHaveBeenCalledWith("00000000-0000-4000-8000-000000000001", {
      plan: "free",
    });
  });

  it("track scrubs email + every deny-list key before transmission", async () => {
    const a = await import("./analytics");
    a.initAnalytics();
    a.track("signed_up", {
      email: "user@example.com",
      user_email: "user@example.com",
      prompt: "should I sell NVDA?",
      amount_usd: 5000,
      balance: 12000,
      source: "landing", // safe funnel prop survives
    });
    expect(capture).toHaveBeenCalledWith("signed_up", { source: "landing" });
  });

  it("nothing sensitive appears in ANY payload that would hit the wire", async () => {
    const a = await import("./analytics");
    a.initAnalytics();
    a.identifyUser("uuid-2", { email: "leak@example.com" });
    a.track("score_viewed", { ticker: "TSLA", equity: 99999 });
    a.capturePageview("https://mindmarket.app/portfolios/abc?code=oauth-secret#frag");
    const wire = JSON.stringify([identify.mock.calls, capture.mock.calls]);
    expect(wire).not.toContain("example.com");
    expect(wire).not.toContain("TSLA");
    expect(wire).not.toContain("99999");
    expect(wire).not.toContain("oauth-secret");
  });
});

describe("library-attached URL properties (review-caught leak path)", () => {
  it("init registers a sanitize_properties hook and disables pageleave", async () => {
    const a = await import("./analytics");
    a.initAnalytics();
    expect(init).toHaveBeenCalledTimes(1);
    const cfg = init.mock.calls[0][1] as Record<string, unknown>;
    expect(cfg.capture_pageleave).toBe(false);
    expect(cfg.autocapture).toBe(false);
    expect(typeof cfg.sanitize_properties).toBe("function");
  });

  it("the hook scrubs $current_url query/hash and templates path UUIDs", async () => {
    const a = await import("./analytics");
    const scrubbed = a.sanitizeEventProps({
      $current_url:
        "https://mindmarket.app/copilot?q=should%20I%20sell%20NVDA#frag",
      $referrer: "https://mindmarket.app/login?code=oauth-secret",
      $pathname: "/portfolios/3f2a1b4c-1234-4abc-8def-0123456789ab/risk",
      event_prop: "kept",
    });
    expect(scrubbed.$current_url).toBe("https://mindmarket.app/copilot");
    expect(scrubbed.$referrer).toBe("https://mindmarket.app/login");
    expect(scrubbed.$pathname).toBe("/portfolios/:id/risk");
    expect(scrubbed.event_prop).toBe("kept");
    expect(JSON.stringify(scrubbed)).not.toContain("NVDA");
    expect(JSON.stringify(scrubbed)).not.toContain("oauth-secret");
  });

  it("pageview URLs template portfolio UUIDs out of the path", async () => {
    const a = await import("./analytics");
    expect(
      a.sanitizePageviewUrl(
        "https://mindmarket.app/portfolios/3f2a1b4c-1234-4abc-8def-0123456789ab/edit?x=1",
      ),
    ).toBe("https://mindmarket.app/portfolios/:id/edit");
  });
});
