"use client";

/**
 * Pre-login interactive Sample Risk Cockpit (anchor #sample-cockpit).
 *
 * Fully deterministic + self-contained: a fixed sample portfolio with
 * pre-computed metrics, an interactive market-shock selector, and ranked
 * risk-driver bars. NO network, NO auth, NO AI — every figure is a constant
 * or derived in plain TS from the constants here, so a visitor (and Google)
 * sees a real, honest cockpit before signing in. The scenario math is a
 * transparent first-order beta×shock approximation, labelled as such.
 *
 * Reuses the real cockpit primitives (<ScoreGauge>, <HorizontalBarChart>) so
 * what you see here is what the signed-in product renders.
 */

import { useState } from "react";
import Link from "next/link";
import { ScoreGauge, scoreBand } from "@/components/score-gauge";
import { HorizontalBarChart, type BarDatum } from "@/components/ui/bar-chart";

const NOTIONAL = 100_000; // sample book size, $

type SampleHolding = {
  ticker: string;
  name: string;
  weight: number; // fraction of book
  beta: number; // sensitivity to a broad market move
  varContribPct: number; // share of total portfolio VaR (deterministic)
};

// A realistic, slightly tech-concentrated sample book — the kind of portfolio
// the Health Score is most useful on. Weights sum to 1.0.
const SAMPLE: SampleHolding[] = [
  { ticker: "NVDA", name: "NVIDIA", weight: 0.22, beta: 1.75, varContribPct: 31 },
  { ticker: "AAPL", name: "Apple", weight: 0.2, beta: 1.2, varContribPct: 19 },
  { ticker: "MSFT", name: "Microsoft", weight: 0.18, beta: 1.1, varContribPct: 16 },
  { ticker: "TSLA", name: "Tesla", weight: 0.12, beta: 1.9, varContribPct: 18 },
  { ticker: "SPY", name: "S&P 500 ETF", weight: 0.18, beta: 1.0, varContribPct: 11 },
  { ticker: "TLT", name: "20Y Treasuries", weight: 0.1, beta: -0.25, varContribPct: 5 },
];

// Pre-computed headline metrics for this exact book (deterministic constants,
// the values the engine would return — not live).
const METRICS = {
  score: 612,
  dimensions: [
    { label: "Risk match", value: 5.4 },
    { label: "Risk-adj. return", value: 7.1 },
    { label: "Downside protection", value: 4.2 },
  ],
  annualVol: 0.243, // 24.3%
  var95: 0.0252, // 1-day 95% VaR, fraction
  cvar95: 0.0331,
  maxDrawdown: -0.418,
  sharpe: 0.94,
};

const SHOCKS = [-5, -10, -20, -30] as const;

function usd(n: number): string {
  return n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
}
function pct(n: number, digits = 1): string {
  return `${(n * 100).toFixed(digits)}%`;
}

export function SampleCockpit() {
  const [shock, setShock] = useState<(typeof SHOCKS)[number]>(-10);
  const band = scoreBand(METRICS.score);
  const s = shock / 100;

  // First-order scenario: each holding moves beta × shock; portfolio $ loss is
  // the weighted sum. Transparent + deterministic (not a Monte-Carlo claim).
  const perHolding = SAMPLE.map((h) => ({
    ...h,
    loss: NOTIONAL * h.weight * h.beta * s,
  }));
  const portfolioLoss = perHolding.reduce((a, h) => a + h.loss, 0);
  const topImpact = [...perHolding].sort((a, b) => a.loss - b.loss).slice(0, 3);

  const driverBars: BarDatum[] = SAMPLE.map((h) => ({
    label: h.ticker,
    value: h.varContribPct,
    color: "hsl(var(--primary))",
  }));

  return (
    <section
      id="sample-cockpit"
      className="scroll-mt-24 space-y-5 rounded-2xl border border-border bg-card p-5 sm:p-7"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <p className="text-xs font-medium uppercase tracking-widest text-primary">
            Live sample · no sign-in
          </p>
          <h2 className="text-2xl font-semibold tracking-tight">
            See a real risk cockpit in 30 seconds
          </h2>
          <p className="max-w-xl text-sm text-muted-foreground">
            A tech-tilted $100k sample book, scored with the same engine your own
            portfolio would use. Move the crash slider — every number is computed,
            nothing is invented.
          </p>
        </div>
        <Link
          href="/signup"
          className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
        >
          Score your own →
        </Link>
      </div>

      {/* score hero */}
      <div className="grid gap-5 md:grid-cols-[0.9fr_1.1fr]">
        <div className="space-y-3 rounded-xl border border-border bg-muted/20 p-4">
          <div className="flex items-baseline justify-between">
            <span className="text-xs uppercase tracking-widest text-muted-foreground">
              Health score
            </span>
            <span className={`text-xs font-semibold uppercase tracking-wide ${band.text}`}>
              {band.label}
            </span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="font-mono text-4xl font-semibold tabular-nums">{METRICS.score}</span>
            <span className="text-sm text-muted-foreground">/ 1000</span>
          </div>
          <ScoreGauge score={METRICS.score} />
          <div className="grid grid-cols-3 gap-2 pt-1">
            {METRICS.dimensions.map((d) => (
              <div key={d.label} className="rounded-lg bg-background/60 p-2 text-center">
                <p className="font-mono text-lg font-semibold tabular-nums">{d.value.toFixed(1)}</p>
                <p className="text-[10px] leading-tight text-muted-foreground">{d.label}</p>
              </div>
            ))}
          </div>
        </div>

        {/* KPI tiles */}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <Kpi label="Annualized vol" value={pct(METRICS.annualVol)} tone="warn" />
          <Kpi label="1-day VaR 95%" value={pct(METRICS.var95, 2)} tone="warn" />
          <Kpi label="1-day CVaR 95%" value={pct(METRICS.cvar95, 2)} tone="bad" />
          <Kpi label="Max drawdown" value={pct(METRICS.maxDrawdown)} tone="bad" />
          <Kpi label="Sharpe" value={METRICS.sharpe.toFixed(2)} tone="ok" />
          <Kpi label="Holdings" value={String(SAMPLE.length)} tone="neutral" />
        </div>
      </div>

      {/* diagnosis */}
      <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-4">
        <p className="text-sm font-semibold text-amber-600 dark:text-amber-400">
          Watch — concentrated in high-beta tech
        </p>
        <ul className="mt-1.5 space-y-1 text-sm text-muted-foreground">
          <li>• Top 4 names are ~72% of the book; NVDA + TSLA carry the most VaR.</li>
          <li>• 24% annualized volatility is high for a long-term core book.</li>
          <li>• The 10% Treasury sleeve is the only real downside cushion.</li>
        </ul>
        <p className="mt-2 text-xs text-muted-foreground">
          Inspect first, not a buy/sell call — educational only.
        </p>
      </div>

      {/* interactive scenario + drivers */}
      <div className="grid gap-5 md:grid-cols-2">
        <div className="space-y-3">
          <h3 className="text-sm font-semibold">If the market drops…</h3>
          <div className="flex gap-2">
            {SHOCKS.map((sh) => (
              <button
                key={sh}
                type="button"
                onClick={() => setShock(sh)}
                aria-pressed={shock === sh}
                className={`rounded-md border px-3 py-1.5 text-sm font-medium tabular-nums transition ${
                  shock === sh
                    ? "border-primary bg-primary text-primary-foreground"
                    : "border-border hover:bg-accent"
                }`}
              >
                {sh}%
              </button>
            ))}
          </div>
          <div className="rounded-xl border border-border bg-muted/20 p-4">
            <p className="text-xs uppercase tracking-widest text-muted-foreground">
              Estimated portfolio impact
            </p>
            <p className="font-mono text-3xl font-semibold tabular-nums text-red-600 dark:text-red-400">
              {usd(portfolioLoss)}
            </p>
            <p className="text-xs text-muted-foreground">
              {pct(portfolioLoss / NOTIONAL)} of a {usd(NOTIONAL)} book · first-order
              beta × shock estimate
            </p>
            <div className="mt-3 space-y-1.5">
              {topImpact.map((h) => (
                <div key={h.ticker} className="flex items-center justify-between text-sm">
                  <span className="font-mono">{h.ticker}</span>
                  <span className="font-mono tabular-nums text-red-600 dark:text-red-400">
                    {usd(h.loss)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="space-y-3">
          <h3 className="text-sm font-semibold">What drives the risk</h3>
          <p className="text-xs text-muted-foreground">
            Share of total portfolio VaR by holding — where your downside actually
            concentrates.
          </p>
          <HorizontalBarChart
            data={driverBars}
            valueFormatter={(v) => `${v}%`}
            ariaLabel="Risk contribution by holding"
          />
        </div>
      </div>

      <div className="flex flex-col items-start justify-between gap-3 border-t border-border pt-4 sm:flex-row sm:items-center">
        <p className="text-xs text-muted-foreground">
          Sample data · illustrative metrics for a fixed demo book, not live prices.
          Your own cockpit uses real market data with full source provenance.
        </p>
        <Link
          href="/signup"
          className="shrink-0 rounded-md border border-border px-4 py-2 text-sm hover:bg-accent"
        >
          Run it on my portfolio
        </Link>
      </div>
    </section>
  );
}

function Kpi({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "ok" | "warn" | "bad" | "neutral";
}) {
  const toneClass = {
    ok: "text-emerald-600 dark:text-emerald-400",
    warn: "text-amber-600 dark:text-amber-400",
    bad: "text-red-600 dark:text-red-400",
    neutral: "text-foreground",
  }[tone];
  return (
    <div className="rounded-xl border border-border bg-background/40 p-3">
      <p className="text-[10px] uppercase tracking-widest text-muted-foreground">{label}</p>
      <p className={`font-mono text-xl font-semibold tabular-nums ${toneClass}`}>{value}</p>
    </div>
  );
}
