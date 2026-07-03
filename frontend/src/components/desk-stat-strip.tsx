"use client";

/**
 * Desk stat strip — the dense mono one-liner a risk desk reads first,
 * exposure before risk: how BIG is the book and how levered, then how risky.
 * Pure display over numbers the page already fetched (no requests here).
 * Recipe follows <MarketStatusBar/> (mono, overflow-x scroll, uppercase
 * micro-labels).
 */

import type { PortfolioMetrics } from "@/lib/schemas";
import type { RiskReport } from "@/lib/queries";

export type DeskStatItem = {
  label: string;
  value: string;
  tone?: "ok" | "warn" | "bad";
};

const TONE: Record<NonNullable<DeskStatItem["tone"]>, string> = {
  ok: "text-[hsl(var(--success))]",
  warn: "text-[hsl(var(--warning))]",
  bad: "text-destructive",
};

export function DeskStatStrip({ items, asOf }: { items: DeskStatItem[]; asOf?: string | null }) {
  const visible = items.filter((it) => it.value !== "—");
  if (visible.length === 0) return null;
  return (
    <div
      data-testid="desk-stat-strip"
      className="flex items-center gap-x-5 overflow-x-auto whitespace-nowrap rounded-lg border border-border bg-muted/40 px-4 py-2 font-mono text-[11px] tabular-nums text-foreground"
    >
      {asOf && (
        <span className="uppercase tracking-wider text-muted-foreground/70">as of {asOf}</span>
      )}
      {visible.map((it) => (
        <span key={it.label}>
          <span className="uppercase tracking-wider text-muted-foreground/70">{it.label}</span>{" "}
          <span className={it.tone ? TONE[it.tone] : undefined}>{it.value}</span>
        </span>
      ))}
    </div>
  );
}

// ── formatting (null → "—" so the strip degrades cell-by-cell) ────────
const usd = (v: number | null | undefined) =>
  v == null
    ? "—"
    : v.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const pct = (v: number | null | undefined, d = 1) => (v == null ? "—" : `${(v * 100).toFixed(d)}%`);
const num = (v: number | null | undefined, d = 2) => (v == null ? "—" : v.toFixed(d));

/**
 * PORTFOLIO beta = the SPY row of the portfolio-level factor regression.
 * NEVER `report.betas` — that is the PER-HOLDING beta map ({ticker: βᵢ}),
 * and "first entry" would show an arbitrary holding's beta.
 */
export function portfolioBeta(report: RiskReport): number | null {
  const row = report.factor_betas.find((f) => f.factor === "SPY");
  return row?.beta ?? null;
}

/** Desk strip for the full risk report (top of /risk). */
export function ReportDeskStrip({ report }: { report: RiskReport }) {
  const beta = portfolioBeta(report);
  const total = report.total_value ?? null;
  const net = report.net_equity ?? null;
  // The regression beta is estimated on the EQUITY book (cash never enters
  // the engine's return frame), so dollar-beta multiplies the equity MV,
  // not cash-inclusive gross.
  const equity = total != null ? total - (report.cash_balance ?? 0) : null;
  const lev = total != null && net != null && net > 0 ? total / net : null;
  const items: DeskStatItem[] = [
    { label: "gross", value: usd(total) },
    { label: "net", value: usd(net) },
    {
      label: "lev",
      value: lev != null && lev > 1.0001 ? `${lev.toFixed(2)}×` : "—",
      tone: lev != null && lev > 1.5 ? "warn" : undefined,
    },
    { label: "β", value: num(beta) },
    { label: "β-adj exp", value: beta != null && equity != null ? usd(beta * equity) : "—" },
    { label: "vol", value: pct(report.annual_volatility) },
    // report.var_95/cvar_95 are the Monte-Carlo 21-DAY horizon numbers
    // (RiskEngine mc_horizon=21) — label the horizon, don't imply daily.
    { label: "var95 21d", value: pct(report.var_95), tone: "bad" },
    { label: "cvar95 21d", value: pct(report.cvar_95), tone: "bad" },
    { label: "sharpe", value: num(report.sharpe_ratio) },
    { label: "maxdd", value: pct(report.max_drawdown) },
  ];
  return <DeskStatStrip items={items} asOf={report.rolling_volatility?.series.at(-1)?.date} />;
}

/** Compact desk strip for the dashboard hero (score metrics, no new fetch). */
export function MetricsDeskStrip({ metrics }: { metrics: PortfolioMetrics }) {
  const beta = metrics.beta_to_benchmark ?? null;
  const total = metrics.total_value ?? null;
  const net = metrics.net_equity ?? null;
  const lev = metrics.leverage ?? null;
  const items: DeskStatItem[] = [
    { label: "gross", value: usd(total) },
    { label: "net", value: usd(net) },
    {
      label: "lev",
      value: lev != null && lev > 1.0001 ? `${lev.toFixed(2)}×` : "—",
      tone: lev != null && lev > 1.5 ? "warn" : undefined,
    },
    { label: "β", value: num(beta) },
    // The score's beta is estimated on the levered net-equity return series,
    // so its dollar-beta base is NET equity (β × net = $ move per 100% market
    // move) — algebraically the same exposure the /risk strip shows.
    { label: "β-adj exp", value: beta != null && net != null ? usd(beta * net) : "—" },
    { label: "vol", value: pct(metrics.annual_volatility) },
    // The score endpoint's VaR is the 1-day historical figure — a different
    // horizon than the /risk report's 21-day Monte-Carlo VaR; say so.
    { label: "var95 1d", value: pct(metrics.var_95_daily), tone: "bad" },
    { label: "sharpe", value: num(metrics.sharpe_ratio) },
    { label: "maxdd", value: pct(metrics.max_drawdown) },
  ];
  return <DeskStatStrip items={items} />;
}
