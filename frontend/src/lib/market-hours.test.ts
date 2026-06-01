/**
 * Day/night clock contract.
 *
 * Dates are constructed in UTC and converted to ET by the function under
 * test, so these also prove DST handling: in summer ET = UTC-4 (EDT), in
 * winter ET = UTC-5 (EST). The "day" session is 04:00–20:00 ET (light);
 * the rest is the overnight session (dark). The boundary at 20:00 ET is the
 * same instant as 17:00 PT.
 */

import { describe, expect, it } from "vitest";
import { isDaySession, marketTheme } from "./market-hours";

describe("isDaySession", () => {
  it("is DAY mid-afternoon on a summer weekday (EDT)", () => {
    // Mon 2026-06-01, 14:00 UTC = 10:00 EDT
    expect(isDaySession(new Date("2026-06-01T14:00:00Z"))).toBe(true);
  });

  it("stays DAY through the 4–8pm post-market window (just before 8pm ET)", () => {
    // Mon 2026-06-01, 23:59 UTC = 19:59 EDT
    expect(isDaySession(new Date("2026-06-01T23:59:00Z"))).toBe(true);
  });

  it("flips to NIGHT exactly at 20:00 ET (= 17:00 PT, end exclusive)", () => {
    // Mon 2026-06-01 20:00 EDT = Tue 2026-06-02 00:00 UTC
    expect(isDaySession(new Date("2026-06-02T00:00:00Z"))).toBe(false);
  });

  it("is NIGHT overnight (03:00 ET)", () => {
    // Tue 2026-06-02, 07:00 UTC = 03:00 EDT
    expect(isDaySession(new Date("2026-06-02T07:00:00Z"))).toBe(false);
  });

  it("is DAY again from 04:00 ET (pre-market)", () => {
    // Tue 2026-06-02, 08:00 UTC = 04:00 EDT
    expect(isDaySession(new Date("2026-06-02T08:00:00Z"))).toBe(true);
  });

  it("is a pure time-of-day rule — weekends follow the same clock", () => {
    // Sat 2026-06-06, 19:00 UTC = 15:00 EDT → daytime → light
    expect(isDaySession(new Date("2026-06-06T19:00:00Z"))).toBe(true);
    // Sat 2026-06-07, 01:00 UTC = Fri... 21:00 EDT → night → dark
    expect(isDaySession(new Date("2026-06-07T01:00:00Z"))).toBe(false);
  });

  it("handles winter EST (DST off)", () => {
    // Mon 2026-01-05, 15:00 UTC = 10:00 EST → day
    expect(isDaySession(new Date("2026-01-05T15:00:00Z"))).toBe(true);
    // Tue 2026-01-06, 01:00 UTC = Mon 20:00 EST → night
    expect(isDaySession(new Date("2026-01-06T01:00:00Z"))).toBe(false);
  });
});

describe("marketTheme", () => {
  it("is light by day, dark at night", () => {
    expect(marketTheme(new Date("2026-06-01T14:00:00Z"))).toBe("light"); // 10:00 EDT
    expect(marketTheme(new Date("2026-06-02T07:00:00Z"))).toBe("dark"); // 03:00 EDT
  });
});
