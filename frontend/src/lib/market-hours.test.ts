/**
 * market-hours clock contract.
 *
 * Dates are constructed in UTC and converted to ET by the function under
 * test, so these also prove DST handling: in summer ET = UTC-4 (EDT), in
 * winter ET = UTC-5 (EST). 13:30 UTC is 09:30 EDT (open) but 08:30 EST
 * (closed) — the assertions below pin both regimes.
 */

import { describe, expect, it } from "vitest";
import { isUsMarketOpen, marketTheme } from "./market-hours";

describe("isUsMarketOpen", () => {
  it("is OPEN mid-session on a summer weekday (EDT)", () => {
    // Mon 2026-06-01, 14:00 UTC = 10:00 EDT
    expect(isUsMarketOpen(new Date("2026-06-01T14:00:00Z"))).toBe(true);
  });

  it("is CLOSED just before the 09:30 ET bell", () => {
    // Mon 2026-06-01, 13:29 UTC = 09:29 EDT
    expect(isUsMarketOpen(new Date("2026-06-01T13:29:00Z"))).toBe(false);
  });

  it("is OPEN exactly at 09:30 ET", () => {
    // Mon 2026-06-01, 13:30 UTC = 09:30 EDT
    expect(isUsMarketOpen(new Date("2026-06-01T13:30:00Z"))).toBe(true);
  });

  it("is CLOSED at 16:00 ET (close is exclusive)", () => {
    // Mon 2026-06-01, 20:00 UTC = 16:00 EDT
    expect(isUsMarketOpen(new Date("2026-06-01T20:00:00Z"))).toBe(false);
  });

  it("is CLOSED overnight", () => {
    // Tue 2026-06-02, 03:00 UTC = Mon 23:00 EDT
    expect(isUsMarketOpen(new Date("2026-06-02T03:00:00Z"))).toBe(false);
  });

  it("is CLOSED on weekends", () => {
    // Sat 2026-06-06, 15:00 UTC = 11:00 EDT (would be intraday on a weekday)
    expect(isUsMarketOpen(new Date("2026-06-06T15:00:00Z"))).toBe(false);
  });

  it("handles winter EST (DST off): 14:35 UTC = 09:35 EST → open", () => {
    // Mon 2026-01-05, 14:35 UTC = 09:35 EST
    expect(isUsMarketOpen(new Date("2026-01-05T14:35:00Z"))).toBe(true);
    // 14:00 UTC = 09:00 EST → still closed (before the bell)
    expect(isUsMarketOpen(new Date("2026-01-05T14:00:00Z"))).toBe(false);
  });
});

describe("marketTheme", () => {
  it("is light during the session, dark otherwise", () => {
    expect(marketTheme(new Date("2026-06-01T14:00:00Z"))).toBe("light");
    expect(marketTheme(new Date("2026-06-06T15:00:00Z"))).toBe("dark");
  });
});
