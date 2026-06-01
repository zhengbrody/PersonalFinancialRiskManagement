/**
 * Day/night clock — drives the market-synced theme (Robinhood-style).
 *
 * Product rule: **light during the trading day, dark for the night/overnight
 * session.** Light from 04:00 (pre-market) until 20:00 **America/New_York**
 * (8:00pm ET = 5:00pm PT, i.e. after the 4–8pm post-market window); dark from
 * 20:00 ET through 04:00 ET (the overnight session). The switch is automatic;
 * there is no manual toggle.
 *
 * We read the wall-clock in America/New_York via `Intl` so daylight-saving is
 * handled for us (no hardcoded UTC offset). The rule is a pure time-of-day
 * window — it applies every day (weekends included), matching "white in the
 * daytime, black at night".
 *
 * NOTE: the pre-hydration boot script in `app/layout.tsx` mirrors this exact
 * logic inline (it can't import a module). Keep the two in sync.
 */

const DAY_START_MINUTES = 4 * 60; // 04:00 ET — pre-market opens
const DAY_END_MINUTES = 20 * 60; // 20:00 ET (= 17:00 PT) — post-market ends

/** True during the light "day" session (04:00–20:00 ET); false at night. */
export function isDaySession(now: Date = new Date()): boolean {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(now);

  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  // hour12:false can emit "24" at midnight in some engines — normalise.
  const hour = parseInt(get("hour"), 10) % 24;
  const minute = parseInt(get("minute"), 10);
  const mins = hour * 60 + minute;

  return mins >= DAY_START_MINUTES && mins < DAY_END_MINUTES;
}

/** The theme that matches the current session: light by day, dark at night. */
export function marketTheme(now: Date = new Date()): "light" | "dark" {
  return isDaySession(now) ? "light" : "dark";
}
