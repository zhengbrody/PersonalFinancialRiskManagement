// PostHog product analytics — the beta funnel (signup → onboarding → import →
// first score → Copilot → return). The phc_ key is publishable (ships in the
// browser), so we bake a default + allow env override, mirroring Sentry. Only
// active in PRODUCTION so dev/test never pollute the project. All helpers are
// safe no-ops when disabled / before init.
import posthog from "posthog-js";
import { ANALYTICS_EVENTS, readUtm, type AnalyticsEvent, type Utm } from "./analytics-events";

export const POSTHOG_KEY =
  process.env.NEXT_PUBLIC_POSTHOG_KEY ||
  "phc_At9CsXuTvMjwzUNmm46kDNHuSNQoPkmWGMwkMUg64YkL";
export const POSTHOG_HOST =
  process.env.NEXT_PUBLIC_POSTHOG_HOST || "https://us.i.posthog.com";

export const ANALYTICS_ENABLED =
  process.env.NODE_ENV === "production" && Boolean(POSTHOG_KEY);

let started = false;

export function initAnalytics(): void {
  if (!ANALYTICS_ENABLED || started || typeof window === "undefined") return;
  try {
    posthog.init(POSTHOG_KEY, {
      api_host: POSTHOG_HOST,
      capture_pageview: false, // App Router → manual pageviews (see provider)
      // pageleave adds no funnel value and would auto-attach the full URL.
      capture_pageleave: false,
      person_profiles: "identified_only",
      // Finance UX can expose sensitive text through buttons, forms, and URLs.
      // Keep analytics to explicit, reviewed `track(...)` calls only.
      autocapture: false,
      // posthog-js attaches $current_url = location.href (query included!) to
      // EVERY event, bypassing redactProps — this hook scrubs those
      // library-attached URL properties on the way out (review-caught:
      // /copilot?q=<prompt> deep links would otherwise leak the prompt).
      sanitize_properties: (props) => sanitizeEventProps(props),
    });
    started = true;
  } catch {
    /* analytics must never break the app */
  }
}

// Defense-in-depth: even though every call site is reviewed to pass only safe,
// aggregate props, we ALSO scrub any property whose key looks like investment
// content (a ticker, a dollar value, a raw prompt, an id). So a future careless
// `track("x", { ticker })` can never leak — analytics stays funnel-only.
const _DENY_KEY_SUBSTRINGS = [
  "ticker",
  "symbol",
  "holding",
  "prompt",
  "question",
  "message",
  "query",
  "portfolio_id",
  "portfolioid",
  "email",
  "dollar",
  "usd",
  "amount",
  "balance",
  "equity",
  "notional",
  "price",
  "premium",
  "strike",
  "cost",
];

// Explicitly-safe keys that bypass the deny-list. `holdings_band` is a coarse
// band ("1-5"/"6-10"/"11+"), NOT a count or a name — but it contains the
// substring "holding", so without this exception the deny-list would silently
// drop it (the bug this allowlist fixes). Keep this set tiny + reviewed.
const _ALLOW_KEYS = new Set(["holdings_band"]);

export function redactProps(
  props?: Record<string, unknown>,
): Record<string, unknown> | undefined {
  if (!props) return props;
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(props)) {
    const k = key.toLowerCase();
    if (_ALLOW_KEYS.has(k)) {
      out[key] = value;
      continue;
    }
    if (_DENY_KEY_SUBSTRINGS.some((d) => k.includes(d))) continue; // drop sensitive
    out[key] = value;
  }
  return out;
}

// Library-attached URL properties that ride on every posthog-js event.
const _URL_PROP_KEYS = [
  "$current_url",
  "$referrer",
  "$initial_current_url",
  "$initial_referrer",
] as const;

/**
 * Scrub the properties posthog-js itself attaches to every event: URL props
 * lose query/hash (OAuth codes, ?q= prompts) and dynamic path segments
 * (portfolio UUIDs) are templated to ":id" so no per-object identifier is
 * tied to the person. Applied via `sanitize_properties` in init, so it runs
 * on EVERY outgoing event — including ones this module didn't send.
 */
export function sanitizeEventProps(
  props: Record<string, unknown>,
): Record<string, unknown> {
  const out = { ...props };
  for (const key of _URL_PROP_KEYS) {
    if (typeof out[key] === "string") {
      out[key] = sanitizePageviewUrl(out[key] as string);
    }
  }
  if (typeof out["$pathname"] === "string") {
    out["$pathname"] = maskDynamicPathSegments(out["$pathname"] as string);
  }
  return out;
}

const _UUID_SEGMENT =
  /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi;

/** Template dynamic path segments (e.g. /portfolios/<uuid>/risk → /portfolios/:id/risk). */
export function maskDynamicPathSegments(path: string): string {
  return path.replace(_UUID_SEGMENT, ":id");
}

export function track(event: AnalyticsEvent, props?: Record<string, unknown>): void {
  if (!started) return;
  try {
    posthog.capture(event, redactProps(props));
  } catch {
    /* ignore */
  }
}

// ── first-touch UTM attribution (session-safe storage) ──────────────────────
// Save the FIRST visit's allowlisted UTM to sessionStorage so a later signup can
// be attributed to the campaign that brought the user in. Only the four UTM keys
// are ever stored — never `code`, tokens, tickers, or any other query param.
const _FIRST_UTM_KEY = "mm_first_utm";

export function captureFirstTouchUtm(params: URLSearchParams): void {
  if (typeof window === "undefined") return;
  try {
    if (window.sessionStorage.getItem(_FIRST_UTM_KEY)) return; // first-touch only
    const utm = readUtm(params);
    if (Object.keys(utm).length === 0) return;
    window.sessionStorage.setItem(_FIRST_UTM_KEY, JSON.stringify(utm));
  } catch {
    /* storage unavailable — attribution is best-effort */
  }
}

export function getFirstTouchUtm(): Utm {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.sessionStorage.getItem(_FIRST_UTM_KEY);
    return raw ? (JSON.parse(raw) as Utm) : {};
  } catch {
    return {};
  }
}

// ── returning-user signal ───────────────────────────────────────────────────
// Fires `returned_7d` once when a known visitor comes back after ≥7 days. Only a
// timestamp is stored locally (no PII); the event carries a coarse away-bucket.
const _LAST_SEEN_KEY = "mm_last_seen";
const _DAY_MS = 24 * 60 * 60 * 1000;

export function maybeTrackReturn(now: number = Date.now()): void {
  if (typeof window === "undefined") return;
  try {
    const prev = Number(window.localStorage.getItem(_LAST_SEEN_KEY) || 0);
    window.localStorage.setItem(_LAST_SEEN_KEY, String(now));
    if (prev && now - prev >= 7 * _DAY_MS) {
      const days = (now - prev) / _DAY_MS;
      track(ANALYTICS_EVENTS.returned_7d, { away_bucket: days >= 30 ? "30d+" : "7-30d" });
    }
  } catch {
    /* storage unavailable */
  }
}

export function identifyUser(id: string, props?: Record<string, unknown>): void {
  if (!started) return;
  try {
    // Same defense-in-depth as track(): person properties go through the
    // deny-list scrub, so email / tickers / amounts can never be attached to
    // the PostHog identity even by a careless future call site. The id
    // itself must be the opaque Supabase UUID.
    posthog.identify(id, redactProps(props));
  } catch {
    /* ignore */
  }
}

export function resetAnalytics(): void {
  if (!started) return;
  try {
    posthog.reset();
  } catch {
    /* ignore */
  }
}

export function capturePageview(url: string): void {
  if (!started) return;
  try {
    const safeUrl = sanitizePageviewUrl(url);
    posthog.capture("$pageview", { $current_url: safeUrl });
  } catch {
    /* ignore */
  }
}

/**
 * Strip query strings and hashes before analytics. This prevents OAuth
 * callback codes, future ticker query params, or campaign/user identifiers
 * from leaking into PostHog while preserving route-level funnel analysis.
 */
export function sanitizePageviewUrl(url: string): string {
  try {
    const parsed = new URL(url);
    return `${parsed.origin}${maskDynamicPathSegments(parsed.pathname)}`;
  } catch {
    const bare = url.split("#", 1)[0]?.split("?", 1)[0] ?? url;
    return maskDynamicPathSegments(bare);
  }
}
