import { afterEach, describe, expect, it } from "vitest";
import { ANALYTICS_EVENTS, holdingsBand, readUtm, UTM_KEYS } from "./analytics-events";
import { captureFirstTouchUtm, getFirstTouchUtm, redactProps } from "./analytics";

function stubSessionStorage() {
  const store = new Map<string, string>();
  Object.defineProperty(window, "sessionStorage", {
    configurable: true,
    value: {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => store.set(k, v),
      removeItem: (k: string) => store.delete(k),
      clear: () => store.clear(),
    },
  });
  return store;
}

describe("holdingsBand", () => {
  it("maps a count to a coarse band, never the exact number", () => {
    expect(holdingsBand(0)).toBe("0");
    expect(holdingsBand(-3)).toBe("0");
    expect(holdingsBand(1)).toBe("1-5");
    expect(holdingsBand(5)).toBe("1-5");
    expect(holdingsBand(6)).toBe("6-10");
    expect(holdingsBand(10)).toBe("6-10");
    expect(holdingsBand(11)).toBe("11+");
    expect(holdingsBand(250)).toBe("11+");
    expect(holdingsBand(NaN)).toBe("0");
  });
});

describe("readUtm — allowlist only", () => {
  it("extracts ONLY the four utm_* params", () => {
    const p = new URLSearchParams(
      "utm_source=twitter&utm_medium=social&utm_campaign=launch&utm_content=hero",
    );
    expect(readUtm(p)).toEqual({
      utm_source: "twitter",
      utm_medium: "social",
      utm_campaign: "launch",
      utm_content: "hero",
    });
    expect(UTM_KEYS).toHaveLength(4);
  });

  it("never reads OAuth code, access_token, ticker, or any other query key", () => {
    const p = new URLSearchParams(
      "utm_source=google&code=oauth-secret&access_token=abc123&ticker=NVDA&utm_term=blocked&q=should+I+sell",
    );
    const out = readUtm(p);
    expect(out).toEqual({ utm_source: "google" });
    const serialized = JSON.stringify(out);
    expect(serialized).not.toContain("oauth-secret");
    expect(serialized).not.toContain("abc123");
    expect(serialized).not.toContain("NVDA");
    // utm_term is NOT in the allowlist (only source/medium/campaign/content).
    expect(out).not.toHaveProperty("utm_term");
  });

  it("returns {} when there are no utm params", () => {
    expect(readUtm(new URLSearchParams("code=x&ticker=AAPL"))).toEqual({});
  });
});

describe("property filter — holdings_band vs deny-list", () => {
  it("keeps the compliant holdings_band even though it contains 'holding'", () => {
    expect(redactProps({ holdings_band: "6-10" })).toEqual({ holdings_band: "6-10" });
  });

  it("still drops an exact holdings count / holding name", () => {
    expect(redactProps({ holdings: 7 })).toEqual({});
    expect(redactProps({ holdings_count: 7 })).toEqual({});
    expect(redactProps({ holding_name: "NVDA" })).toEqual({});
  });

  it("keeps utm + funnel props, drops sensitive, alongside a band", () => {
    const out = redactProps({
      holdings_band: "1-5",
      utm_source: "twitter",
      method: "email",
      error_category: "weak_password",
      ticker: "TSLA",
      amount_usd: 5000,
    });
    expect(out).toEqual({
      holdings_band: "1-5",
      utm_source: "twitter",
      method: "email",
      error_category: "weak_password",
    });
  });
});

describe("first-touch UTM (session-safe storage)", () => {
  afterEach(() => {
    // @ts-expect-error restore
    delete window.sessionStorage;
  });

  it("stores only the FIRST touch's allowlisted UTM, then is stable", () => {
    stubSessionStorage();
    captureFirstTouchUtm(new URLSearchParams("utm_source=twitter&utm_campaign=launch&code=secret"));
    expect(getFirstTouchUtm()).toEqual({ utm_source: "twitter", utm_campaign: "launch" });
    // A later visit with different UTM must NOT overwrite first-touch.
    captureFirstTouchUtm(new URLSearchParams("utm_source=google"));
    expect(getFirstTouchUtm()).toEqual({ utm_source: "twitter", utm_campaign: "launch" });
    // No non-UTM key was ever stored.
    expect(JSON.stringify(getFirstTouchUtm())).not.toContain("secret");
  });

  it("stores nothing when there is no UTM", () => {
    stubSessionStorage();
    captureFirstTouchUtm(new URLSearchParams("code=oauth&ticker=NVDA"));
    expect(getFirstTouchUtm()).toEqual({});
  });
});

describe("ANALYTICS_EVENTS catalog", () => {
  it("contains all 17 funnel events", () => {
    const funnel = [
      "landing_viewed",
      "hero_cta_clicked",
      "demo_started",
      "demo_interacted",
      "public_check_started",
      "public_check_completed",
      "signup_started",
      "signup_completed",
      "signup_failed",
      "onboarding_started",
      "csv_imported",
      "portfolio_created",
      "first_score_completed",
      "risk_report_opened",
      "copilot_message_sent",
      "digest_opted_in",
      "returned_7d",
    ];
    for (const e of funnel) {
      expect(Object.values(ANALYTICS_EVENTS)).toContain(e);
    }
  });

  it("every value equals its key (no drift)", () => {
    for (const [k, v] of Object.entries(ANALYTICS_EVENTS)) {
      expect(v).toBe(k);
    }
  });
});
