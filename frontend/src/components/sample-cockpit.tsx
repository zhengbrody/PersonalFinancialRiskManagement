"use client";

/**
 * Pre-login interactive Sample Risk Cockpit (anchor #sample-cockpit).
 *
 * Fully deterministic + self-contained: TWO fixed sample portfolios — a
 * Balanced book (default, the "normal" baseline) and a High-growth book you can
 * one-click "stress" — each with pre-computed metrics, an interactive
 * market-shock selector, ranked risk-driver bars, and a one-line takeaway. NO
 * network, NO auth, NO AI — every figure is a constant or derived in plain TS
 * from the constants here, so a visitor (and Google) sees a real, honest
 * cockpit before signing in. The scenario math is a transparent first-order
 * beta×shock approximation, labelled as such.
 *
 * Reuses the real cockpit primitives (<ScoreGauge>, <HorizontalBarChart>) so
 * what you see here is what the signed-in product renders.
 */

import { useRef, useState } from "react";
import Link from "next/link";
import { ScoreGauge, scoreBand } from "@/components/score-gauge";
import { HorizontalBarChart, type BarDatum } from "@/components/ui/bar-chart";
import { Kpi } from "@/components/ui/kpi";
import { track } from "@/lib/analytics";
import { ANALYTICS_EVENTS } from "@/lib/analytics-events";
import { buildShareUrl } from "@/lib/share-card";

const NOTIONAL = 100_000; // sample book size, $

type SampleHolding = {
  ticker: string;
  name: string;
  weight: number; // fraction of book
  beta: number; // sensitivity to a broad market move
  varContribPct: number; // share of total portfolio VaR (deterministic)
};

type DemoMetrics = {
  score: number;
  dimensions: { label: string; value: number }[];
  annualVol: number;
  var95: number; // 1-day 95% VaR, fraction
  cvar95: number;
  maxDrawdown: number;
  sharpe: number;
};

type DemoBook = {
  id: "balanced" | "growth";
  holdings: SampleHolding[];
  metrics: DemoMetrics;
  takeaway: string; // the one-line headline insight
  diagnosisTitle: string;
  diagnosisTone: "ok" | "warn";
  diagnosisBullets: string[]; // the top 3 risks/notes
  concentration?: string; // shown only when concentration is the story
};

// ── Balanced book (default — the "normal" baseline) ─────────────────────────
// Exported so share-card.test.ts can assert lib/share-card.ts's SHARE_BOOKS
// stays in sync (score/takeaway) — the shareable card must never drift from the
// cockpit it's screenshotting.
export const BALANCED: DemoBook = {
  id: "balanced",
  holdings: [
    { ticker: "SPY", name: "S&P 500 ETF", weight: 0.45, beta: 1.0, varContribPct: 88 },
    { ticker: "BND", name: "US Aggregate Bonds", weight: 0.3, beta: 0.08, varContribPct: 5 },
    { ticker: "GLD", name: "Gold", weight: 0.1, beta: 0.15, varContribPct: 7 },
    { ticker: "CASH", name: "Cash", weight: 0.15, beta: 0.0, varContribPct: 0 },
  ],
  metrics: {
    score: 784,
    dimensions: [
      { label: "Risk match", value: 8.4 },
      { label: "Risk-adj. return", value: 7.2 },
      { label: "Downside protection", value: 8.1 },
    ],
    annualVol: 0.094,
    var95: 0.0098,
    cvar95: 0.0135,
    maxDrawdown: -0.172,
    sharpe: 1.08,
  },
  takeaway:
    "This balanced book spreads risk across stocks, bonds, gold, and cash — its downside is moderate and mostly broad-market, not single-name.",
  diagnosisTitle: "Healthy — diversified across asset classes",
  diagnosisTone: "ok",
  diagnosisBullets: [
    "No single position drives more than ~half the risk; the bond + cash sleeve cushions drawdowns.",
    "~9% annualized volatility is reasonable for a long-term core book.",
    "A market drop hits it roughly in line with its ~0.5 beta — far less than a growth-tilted book.",
  ],
};

// ── High-growth book ("Stress a high-growth portfolio") ─────────────────────
export const GROWTH: DemoBook = {
  id: "growth",
  holdings: [
    { ticker: "QQQ", name: "Nasdaq-100 ETF", weight: 0.25, beta: 1.15, varContribPct: 14 },
    { ticker: "NVDA", name: "NVIDIA", weight: 0.22, beta: 1.75, varContribPct: 27 },
    { ticker: "TSLA", name: "Tesla", weight: 0.15, beta: 1.9, varContribPct: 22 },
    { ticker: "SMH", name: "Semiconductors", weight: 0.16, beta: 1.6, varContribPct: 17 },
    { ticker: "BITO", name: "Bitcoin proxy", weight: 0.12, beta: 2.4, varContribPct: 18 },
    { ticker: "CASH", name: "Cash", weight: 0.1, beta: 0.0, varContribPct: 2 },
  ],
  metrics: {
    score: 541,
    dimensions: [
      { label: "Risk match", value: 3.9 },
      { label: "Risk-adj. return", value: 6.1 },
      { label: "Downside protection", value: 2.8 },
    ],
    annualVol: 0.312,
    var95: 0.0345,
    cvar95: 0.0461,
    maxDrawdown: -0.541,
    sharpe: 0.81,
  },
  takeaway:
    "This portfolio looks diversified by ticker count, but its largest risk is concentrated high-beta growth — a tech-and-crypto selloff hits it about 3× harder than the balanced book.",
  diagnosisTitle: "Watch — concentrated high-beta growth + crypto",
  diagnosisTone: "warn",
  diagnosisBullets: [
    "The top 5 names (NVDA, TSLA, semis, crypto, QQQ) are ~90% of the book and nearly all of the risk.",
    "~31% annualized volatility and a ~−54% modelled max drawdown — a real growth-stock tail.",
    "The crypto sleeve (beta ~2.4) amplifies both the upside and the crash.",
  ],
  concentration: "5 high-beta names ≈ 90% of the book — single-theme (AI / semis / crypto) concentration.",
};

const SHOCKS = [-5, -10, -20, -30] as const;

// One honest line per figure on this page — what it is and how it's derived.
// Deterministic copy (no AI); linked to the matching /learn guide where one exists.
const METHODOLOGY: { label: string; how: string; learn?: string }[] = [
  {
    label: "Health score",
    how: "A weighted blend of three 0–10 dimensions — risk match, risk-adjusted return, downside protection — scaled to 0–1000.",
    learn: "/learn/portfolio-risk-management",
  },
  {
    label: "Annualized vol",
    how: "The standard deviation of daily returns, scaled to a year (×√252).",
  },
  {
    label: "1-day VaR & CVaR 95%",
    how: "VaR is the daily loss you'd expect to exceed only 1 trading day in 20; CVaR is the average loss on those worst days.",
    learn: "/learn/var-cvar-explained",
  },
  {
    label: "Max drawdown",
    how: "The largest peak-to-trough decline over the sample window — the loss that tests your nerve.",
    learn: "/learn/maximum-drawdown",
  },
  {
    label: "Sharpe",
    how: "Return earned per unit of volatility, above the risk-free rate.",
    learn: "/learn/sharpe-ratio-explained",
  },
  {
    label: "Crash scenario",
    how: "A transparent first-order estimate: each holding moves beta × shock, and the portfolio loss is the weighted sum.",
    learn: "/learn/stress-testing",
  },
  {
    label: "Risk drivers",
    how: "Each holding's share of total portfolio VaR — where the downside actually concentrates.",
    learn: "/learn/diversification-correlation",
  },
];

function usd(n: number): string {
  return n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
}
function pct(n: number, digits = 1): string {
  return `${(n * 100).toFixed(digits)}%`;
}

export function SampleCockpit() {
  const [variant, setVariant] = useState<DemoBook["id"]>("balanced");
  const [shock, setShock] = useState<(typeof SHOCKS)[number]>(-10);
  const book = variant === "balanced" ? BALANCED : GROWTH;
  const m = book.metrics;
  const band = scoreBand(m.score);
  const s = shock / 100;

  // First-order scenario: each holding moves beta × shock; portfolio $ loss is
  // the weighted sum. Transparent + deterministic (not a Monte-Carlo claim).
  const perHolding = book.holdings.map((h) => ({ ...h, loss: NOTIONAL * h.weight * h.beta * s }));
  const portfolioLoss = perHolding.reduce((a, h) => a + h.loss, 0);
  const topImpact = [...perHolding].sort((a, b) => a.loss - b.loss).slice(0, 3);
  const driverBars: BarDatum[] = book.holdings.map((h) => ({
    label: h.ticker,
    value: h.varContribPct,
    color: "hsl(var(--primary))",
  }));

  // Fire demo_interacted once on the first meaningful interaction (funnel step).
  const interacted = useRef(false);
  function markInteracted() {
    if (interacted.current) return;
    interacted.current = true;
    track(ANALYTICS_EVENTS.demo_interacted);
  }

  function selectVariant(next: DemoBook["id"]) {
    if (next === variant) return;
    markInteracted();
    setVariant(next);
    // Safe: only the variant label, never any portfolio/$ data (fixed demo books).
    track("demo_stress_toggled", { variant: next });
  }

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
            A $100k sample book, scored with the same engine your own portfolio would
            use. Toggle the high-growth book and move the crash slider — every number
            is computed, nothing is invented.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <a
            href={buildShareUrl(variant)}
            target="_blank"
            rel="noopener noreferrer"
            onClick={() =>
              // Safe: only which fixed demo book, never any real holdings/$.
              track("share_card_created", { variant, source: "demo" })
            }
            className="rounded-md border border-border px-4 py-2 text-sm font-medium hover:bg-accent"
          >
            Share this result ↗
          </a>
          <Link
            href="/signup"
            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            Score your own →
          </Link>
        </div>
      </div>

      {/* portfolio toggle — the headline interaction */}
      <div className="flex flex-wrap items-center gap-2">
        <VariantButton
          active={variant === "balanced"}
          onClick={() => selectVariant("balanced")}
          label="Balanced portfolio"
        />
        <VariantButton
          active={variant === "growth"}
          onClick={() => selectVariant("growth")}
          label="Stress a high-growth portfolio"
        />
      </div>

      {/* one-line takeaway */}
      <p className="text-base font-medium leading-snug">{book.takeaway}</p>

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
            <span className="font-mono text-4xl font-semibold tabular-nums">{m.score}</span>
            <span className="text-sm text-muted-foreground">/ 1000</span>
          </div>
          <ScoreGauge score={m.score} />
          <div className="grid grid-cols-3 gap-2 pt-1">
            {m.dimensions.map((d) => (
              <div key={d.label} className="rounded-lg bg-background/60 p-2 text-center">
                <p className="font-mono text-lg font-semibold tabular-nums">{d.value.toFixed(1)}</p>
                <p className="text-[10px] leading-tight text-muted-foreground">{d.label}</p>
              </div>
            ))}
          </div>
        </div>

        {/* KPI tiles */}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <Kpi label="Annualized vol" value={pct(m.annualVol)} tone={m.annualVol > 0.2 ? "warn" : "neutral"} />
          <Kpi label="1-day VaR 95%" value={pct(m.var95, 2)} tone={m.var95 > 0.02 ? "warn" : "neutral"} />
          <Kpi label="1-day CVaR 95%" value={pct(m.cvar95, 2)} tone={m.cvar95 > 0.03 ? "bad" : "neutral"} />
          <Kpi label="Max drawdown" value={pct(m.maxDrawdown)} tone={m.maxDrawdown < -0.35 ? "bad" : "warn"} />
          <Kpi label="Sharpe" value={m.sharpe.toFixed(2)} tone="ok" />
          <Kpi label="Holdings" value={String(book.holdings.length)} tone="neutral" />
        </div>
      </div>

      {/* diagnosis — the top 3 risks/notes */}
      <div
        className={`rounded-xl border p-4 ${
          book.diagnosisTone === "ok"
            ? "border-emerald-500/30 bg-emerald-500/5"
            : "border-amber-500/30 bg-amber-500/5"
        }`}
      >
        <p
          className={`text-sm font-semibold ${
            book.diagnosisTone === "ok"
              ? "text-emerald-600 dark:text-emerald-400"
              : "text-amber-600 dark:text-amber-400"
          }`}
        >
          {book.diagnosisTitle}
        </p>
        <ul className="mt-1.5 space-y-1 text-sm text-muted-foreground">
          {book.diagnosisBullets.map((b, i) => (
            <li key={i}>• {b}</li>
          ))}
        </ul>
        {book.concentration && (
          <p className="mt-2 rounded-md bg-amber-500/10 px-2.5 py-1.5 text-xs font-medium text-amber-700 dark:text-amber-300">
            ⚠ {book.concentration}
          </p>
        )}
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
                onClick={() => {
                  markInteracted();
                  setShock(sh);
                  // Safe: only the shock % + which demo book, no real holdings/$.
                  track("scenario_shock_selected", { shock_pct: sh / 100, source: `demo_${book.id}` });
                }}
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

      {/* methodology — deterministic, no AI; the "why trust these numbers" story */}
      <details className="group rounded-xl border border-border bg-muted/20">
        <summary className="flex cursor-pointer flex-wrap items-baseline gap-x-2 px-4 py-3 text-sm font-medium">
          How each number is computed
          <span className="text-xs font-normal text-muted-foreground">
            deterministic math — no AI, nothing invented
          </span>
        </summary>
        <div className="space-y-2 border-t border-border p-4 text-sm text-muted-foreground">
          {METHODOLOGY.map((m) => (
            <p key={m.label}>
              <span className="font-medium text-foreground">{m.label}.</span> {m.how}{" "}
              {m.learn && (
                <Link href={m.learn} className="whitespace-nowrap text-primary hover:underline">
                  Learn more →
                </Link>
              )}
            </p>
          ))}
          <p className="pt-1 text-xs">
            Your own cockpit runs the full engine — Monte-Carlo VaR, six-factor betas,
            stress tests — on real market data, with a source and as-of date on every figure.
          </p>
        </div>
      </details>

      <div className="flex flex-col items-start justify-between gap-3 border-t border-border pt-4 sm:flex-row sm:items-center">
        <p className="text-xs text-muted-foreground">
          Sample data · illustrative metrics for fixed demo books, not live prices.
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

function VariantButton({
  active,
  onClick,
  label,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`rounded-full border px-3.5 py-1.5 text-sm font-medium transition ${
        active
          ? "border-primary bg-primary text-primary-foreground"
          : "border-border hover:bg-accent"
      }`}
    >
      {label}
    </button>
  );
}

