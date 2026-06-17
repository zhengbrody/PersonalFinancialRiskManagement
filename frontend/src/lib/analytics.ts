// PostHog product analytics — the beta funnel (signup → onboarding → import →
// first score → Copilot → return). The phc_ key is publishable (ships in the
// browser), so we bake a default + allow env override, mirroring Sentry. Only
// active in PRODUCTION so dev/test never pollute the project. All helpers are
// safe no-ops when disabled / before init.
import posthog from "posthog-js";

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
      capture_pageleave: true,
      person_profiles: "identified_only",
      // Finance UX can expose sensitive text through buttons, forms, and URLs.
      // Keep analytics to explicit, reviewed `track(...)` calls only.
      autocapture: false,
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

export function redactProps(
  props?: Record<string, unknown>,
): Record<string, unknown> | undefined {
  if (!props) return props;
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(props)) {
    const k = key.toLowerCase();
    if (_DENY_KEY_SUBSTRINGS.some((d) => k.includes(d))) continue; // drop sensitive
    out[key] = value;
  }
  return out;
}

export function track(event: string, props?: Record<string, unknown>): void {
  if (!started) return;
  try {
    posthog.capture(event, redactProps(props));
  } catch {
    /* ignore */
  }
}

export function identifyUser(id: string, props?: Record<string, unknown>): void {
  if (!started) return;
  try {
    posthog.identify(id, props);
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
    return `${parsed.origin}${parsed.pathname}`;
  } catch {
    return url.split("#", 1)[0]?.split("?", 1)[0] ?? url;
  }
}
