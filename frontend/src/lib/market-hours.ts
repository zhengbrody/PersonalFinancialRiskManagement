/**
 * US-equity market-hours clock — drives the market-synced theme.
 *
 * Product rule: **light** during US regular trading hours (the floor is
 * open, energy is up), **dark** after-hours / overnight / weekends (calm,
 * eye-friendly). The switch is automatic; there is no manual toggle.
 *
 * "Regular hours" = Mon–Fri, 09:30–16:00 **America/New_York**. We read the
 * wall-clock in that zone via `Intl` so daylight-saving is handled for us
 * (no hardcoded UTC offset). Market holidays are intentionally NOT modelled
 * yet — on a holiday the theme follows the clock, not the calendar; adding a
 * holiday calendar is a clean follow-up if it ever matters.
 *
 * NOTE: the pre-hydration boot script in `app/layout.tsx` mirrors this exact
 * logic inline (it can't import a module). Keep the two in sync.
 */

const OPEN_MINUTES = 9 * 60 + 30; // 09:30 ET
const CLOSE_MINUTES = 16 * 60; // 16:00 ET

/** True when the US equity market is in regular trading hours right now. */
export function isUsMarketOpen(now: Date = new Date()): boolean {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(now);

  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  const weekday = get("weekday"); // "Mon" … "Sun"
  if (weekday === "Sat" || weekday === "Sun") return false;

  // hour12:false can emit "24" at midnight in some engines — normalise.
  const hour = parseInt(get("hour"), 10) % 24;
  const minute = parseInt(get("minute"), 10);
  const mins = hour * 60 + minute;

  return mins >= OPEN_MINUTES && mins < CLOSE_MINUTES;
}

/** The theme that matches the current market session. */
export function marketTheme(now: Date = new Date()): "light" | "dark" {
  return isUsMarketOpen(now) ? "light" : "dark";
}
