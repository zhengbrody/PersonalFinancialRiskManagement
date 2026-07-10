/**
 * Public (no-signup) portfolio risk check — flag, API client, and the
 * localStorage bridge that carries anonymous holdings into signup.
 *
 * FEATURE-FLAGGED, DEFAULT OFF: enabling anonymous arbitrary-ticker analysis
 * is a data-licensing decision (see backend/app/api/v1/public_risk.py).
 * `NEXT_PUBLIC_PUBLIC_RISK_CHECK === "true"` turns the UI on; the backend has
 * its own PUBLIC_RISK_CHECK_ENABLED gate.
 *
 * Privacy: holdings live ONLY in the browser (component state + localStorage
 * for the signup handoff) and in the single stateless POST — never Supabase,
 * never analytics (events carry step + holdings_count only).
 */

import { z } from "zod";

import { apiFetch } from "@/lib/api";

export function isPublicRiskCheckEnabled(): boolean {
  return process.env.NEXT_PUBLIC_PUBLIC_RISK_CHECK === "true";
}

export const MAX_PUBLIC_HOLDINGS = 10;

export type AnonHolding = { ticker: string; shares: string };

const STORAGE_KEY = "mm-anon-risk-check-holdings";

export function saveAnonHoldings(rows: AnonHolding[]): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(rows.slice(0, MAX_PUBLIC_HOLDINGS)));
  } catch {
    /* storage unavailable → the handoff simply doesn't happen */
  }
}

export function loadAnonHoldings(): AnonHolding[] {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter(
        (r): r is AnonHolding =>
          !!r && typeof r.ticker === "string" && typeof r.shares === "string",
      )
      .slice(0, MAX_PUBLIC_HOLDINGS);
  } catch {
    return [];
  }
}

export function clearAnonHoldings(): void {
  try {
    window.localStorage.removeItem(STORAGE_KEY);
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
