import type { RiskReport } from "@/lib/queries";

/**
 * PORTFOLIO beta = the SPY row of the portfolio-level factor regression
 * (report.factor_betas). NEVER read `report.betas` for this — that is the
 * PER-HOLDING beta map ({ticker: βᵢ}, one entry per holding), and "first
 * entry" silently shows an arbitrary holding's beta (JSONB key order).
 */
export function portfolioBeta(report: RiskReport): number | null {
  const row = report.factor_betas.find((f) => f.factor === "SPY");
  return row?.beta ?? null;
}
