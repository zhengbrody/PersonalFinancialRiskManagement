/**
 * The CLOSED set of analytics event names. `track()` accepts ONLY these — no
 * arbitrary strings — so a typo or an ad-hoc event name is a compile error, and
 * the funnel stays auditable. Privacy rules (no tickers / shares / portfolio_id
 * / email / prompt / amounts / holding names) are enforced separately by the
 * property filter in analytics.ts; see docs/marketing/analytics-funnel.md.
 */

export const ANALYTICS_EVENTS = {
  // ── acquisition → activation funnel (the 17) ─────────────────────────────
  landing_viewed: "landing_viewed",
  hero_cta_clicked: "hero_cta_clicked",
  demo_started: "demo_started",
  demo_interacted: "demo_interacted",
  public_check_started: "public_check_started",
  public_check_completed: "public_check_completed",
  signup_started: "signup_started",
  signup_completed: "signup_completed",
  signup_failed: "signup_failed",
  onboarding_started: "onboarding_started",
  csv_imported: "csv_imported",
  portfolio_created: "portfolio_created",
  first_score_completed: "first_score_completed",
  risk_report_opened: "risk_report_opened",
  copilot_message_sent: "copilot_message_sent",
  digest_opted_in: "digest_opted_in",
  returned_7d: "returned_7d",

  // ── other product events (kept, now typed) ───────────────────────────────
  signup_oauth_started: "signup_oauth_started",
  research_started: "research_started",
  copilot_handoff_clicked: "copilot_handoff_clicked",
  quant_tab_changed: "quant_tab_changed",
  risk_tab_changed: "risk_tab_changed",
  scenario_shock_selected: "scenario_shock_selected",
  action_simulated: "action_simulated",
  score_change_window: "score_change_window",
  score_viewed: "score_viewed",
  report_export_clicked: "report_export_clicked",
  upgrade_clicked: "upgrade_clicked",
  whatif_loaded_holdings: "whatif_loaded_holdings",
  whatif_run: "whatif_run",
  demo_stress_toggled: "demo_stress_toggled",
  share_card_created: "share_card_created",
  public_check_csv_imported: "public_check_csv_imported",
  public_check_signup_cta: "public_check_signup_cta",
  risk_diagnosis_viewed: "risk_diagnosis_viewed",
  copilot_opened: "copilot_opened",
  copilot_followup_clicked: "copilot_followup_clicked",
  copilot_ask: "copilot_ask",
  // PR5 — kind-only / value-free (no preference values, no insight content)
  copilot_insight_dismissed: "copilot_insight_dismissed",
  copilot_prefs_confirmed: "copilot_prefs_confirmed",
  copilot_prefs_cleared: "copilot_prefs_cleared",
  sticky_cta_clicked: "sticky_cta_clicked",
  markets_sentiment_viewed: "markets_sentiment_viewed",
  // ── portfolio operating system (value-free: no id/name/ticker/$) ─────────
  portfolio_switched: "portfolio_switched",
} as const;

export type AnalyticsEvent = (typeof ANALYTICS_EVENTS)[keyof typeof ANALYTICS_EVENTS];

/**
 * Coarse holdings-count band — NEVER the exact count, never a holding name.
 * Use this everywhere instead of a raw count so a portfolio's size can't be
 * fingerprinted. The exact-count property `holdings`/`holdings_count` is also
 * dropped by the deny-list, so `holdings_band` is the ONLY compliant carrier.
 */
export function holdingsBand(n: number): "0" | "1-5" | "6-10" | "11+" {
  if (!Number.isFinite(n) || n <= 0) return "0";
  if (n <= 5) return "1-5";
  if (n <= 10) return "6-10";
  return "11+";
}

/** The ONLY UTM params allowed into analytics — nothing else from the query. */
export const UTM_KEYS = ["utm_source", "utm_medium", "utm_campaign", "utm_content"] as const;
export type Utm = Partial<Record<(typeof UTM_KEYS)[number], string>>;

/**
 * Extract ONLY the four allowlisted UTM params. Anything else in the query —
 * OAuth `code`, `access_token`, a `ticker`, arbitrary keys — is never read, so
 * it can never reach PostHog. Values are length-bounded (campaign labels).
 */
export function readUtm(params: URLSearchParams): Utm {
  const out: Utm = {};
  for (const k of UTM_KEYS) {
    const v = params.get(k);
    if (v) out[k] = v.slice(0, 120);
  }
  return out;
}
