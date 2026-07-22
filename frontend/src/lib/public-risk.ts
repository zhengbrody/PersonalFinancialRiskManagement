/**
 * Public (no-signup) portfolio risk check — flag, API client, and the
 * short-lived sessionStorage bridge that carries anonymous holdings into signup.
 *
 * FEATURE-FLAGGED, DEFAULT OFF: enabling anonymous arbitrary-ticker analysis
 * is a data-licensing decision (see backend/app/api/v1/public_risk.py).
 * `NEXT_PUBLIC_PUBLIC_RISK_CHECK === "true"` turns the UI on; the backend has
 * its own PUBLIC_RISK_CHECK_ENABLED gate.
 *
 * Privacy: holdings live ONLY in the browser (component state + a 24-hour,
 * tab-scoped sessionStorage handoff) and in the single stateless POST — never Supabase,
 * never analytics (events carry step + holdings_count only).
 */

import { z } from "zod";

import { apiFetch } from "@/lib/api";

export function isPublicRiskCheckEnabled(): boolean {
  return process.env.NEXT_PUBLIC_PUBLIC_RISK_CHECK === "true";
}

export const MAX_PUBLIC_HOLDINGS = 10;

export type AnonHolding = { ticker: string; shares: string };

export const ANON_HANDOFF_STORAGE_KEY = "mm-anon-risk-check-holdings";
export const ANON_HANDOFF_TTL_MS = 24 * 60 * 60 * 1000;

type AnonHandoffEnvelope = {
  v: 1;
  expires_at: number;
  rows: AnonHolding[];
};

export function saveAnonHoldings(rows: AnonHolding[], now = Date.now()): void {
  try {
    const envelope: AnonHandoffEnvelope = {
      v: 1,
      expires_at: now + ANON_HANDOFF_TTL_MS,
      rows: rows.slice(0, MAX_PUBLIC_HOLDINGS),
    };
    window.sessionStorage.setItem(ANON_HANDOFF_STORAGE_KEY, JSON.stringify(envelope));
    window.localStorage.removeItem(ANON_HANDOFF_STORAGE_KEY);
  } catch {
    /* storage unavailable → the handoff simply doesn't happen */
  }
}

export function loadAnonHoldings(now = Date.now()): AnonHolding[] {
  try {
    // One-time privacy cleanup for browsers that used the older indefinite
    // localStorage bridge.  We intentionally do not import that value into the
    // new flow; it is stale and has no trustworthy creation timestamp.
    window.localStorage.removeItem(ANON_HANDOFF_STORAGE_KEY);
    const raw = window.sessionStorage.getItem(ANON_HANDOFF_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as Partial<AnonHandoffEnvelope>;
    if (
      parsed.v !== 1 ||
      typeof parsed.expires_at !== "number" ||
      parsed.expires_at <= now ||
      !Array.isArray(parsed.rows)
    ) {
      clearAnonHoldings();
      return [];
    }
    return parsed.rows
      .filter(
        (r): r is AnonHolding =>
          !!r && typeof r.ticker === "string" && typeof r.shares === "string",
      )
      .slice(0, MAX_PUBLIC_HOLDINGS);
  } catch {
    clearAnonHoldings();
    return [];
  }
}

export function clearAnonHoldings(): void {
  try {
    window.sessionStorage.removeItem(ANON_HANDOFF_STORAGE_KEY);
    window.localStorage.removeItem(ANON_HANDOFF_STORAGE_KEY);
  } catch {
    /* ignore */
  }
}

// ── response schema (mirrors backend/app/schemas/public_risk.py) ──────

export const publicRiskCheckSchema = z.looseObject({
  concentration: z.looseObject({
    top_ticker: z.string().nullable(),
    top_weight: z.number().nullable(),
    hhi: z.number().nullable(),
    effective_holdings: z.number().nullable(),
    weights: z.record(z.string(), z.number()),
  }),
  metrics: z.looseObject({
    total_value: z.number().nullable(),
    annual_volatility: z.number().nullable(),
    var_95_1d: z.number().nullable(),
    cvar_95_1d: z.number().nullable(),
    beta_to_market: z.number().nullable(),
  }),
  stress: z.array(
    z.looseObject({
      market_shock_pct: z.number(),
      est_portfolio_impact_pct: z.number().nullable(),
      est_portfolio_impact_usd: z.number().nullable(),
    }),
  ),
  provenance: z.looseObject({
    as_of: z.string().nullable(),
    observations: z.number(),
    priced: z.array(z.string()),
    missing: z.array(z.string()),
    sources: z.record(z.string(), z.string()),
    window_limited_by: z.string().nullable().optional(),
  }),
  disclaimer: z.string(),
});

export type PublicRiskCheckResult = z.infer<typeof publicRiskCheckSchema>;

export async function runPublicRiskCheck(
  holdings: { ticker: string; shares: number }[],
): Promise<PublicRiskCheckResult> {
  return apiFetch("/api/v1/public/risk_check", {
    method: "POST",
    body: { holdings },
    schema: publicRiskCheckSchema,
  });
}
