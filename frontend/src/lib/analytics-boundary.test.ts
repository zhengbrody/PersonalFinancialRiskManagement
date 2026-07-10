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
