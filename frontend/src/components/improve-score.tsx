"use client";

/**
 * "How to improve this score" — deterministic, biggest-lever-first guidance,
 * computed ENTIRELY from the score response the page already holds (dimensions,
 * metrics, risk_target, concentration, options, leverage). No recompute, no LLM,
 * no invented numbers — each lever quotes a real gap and links to Copilot (a
 * tailored, prefilled question) or Holdings. Educational, never buy/sell advice.
 */

import Link from "next/link";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { ScoreResponse } from "@/lib/schemas";

type Lever = { key: string; sev: number; title: string; detail: string; q: string };

const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : undefined);
const pct0 = (v: number) => `${(v * 100).toFixed(0)}%`;

/** Build the ranked levers from real gaps. Pure + deterministic. */
export function buildLevers(score: ScoreResponse): Lever[] {
  const m = score.metrics;
  const c = score.concentration;
  const rt = (score.risk_target ?? {}) as Record<string, unknown>;
  const targetVol = num(rt.annual_volatility);
  const targetBeta = num(rt.beta);
  const profile = typeof rt.label === "string" ? rt.label : "your profile";

  const vol = num(m.annual_volatility);
  const beta = num(m.beta_to_benchmark);
  const dd = num(m.max_drawdown);
  const sharpe = num(m.sharpe_ratio);
  const leverage = num(m.leverage);
  const topName = num(c?.top_holding_weight) ?? 0;
  const topSector = num(c?.top_sector_weight) ?? 0;

  const levers: Lever[] = [];

  if (c?.top_holding_ticker && topName > 0.25) {
    levers.push({
      key: "concentration",
      sev: topName > 0.45 ? 3 : topName > 0.35 ? 2 : 1,
      title: "Reduce single-name concentration",
      detail: `${c.top_holding_ticker} is ${pct0(topName)} of your book — a shock to one name swings the whole portfolio. Compare downside in the What-if lab with that position scaled down.`,
      q: `How can I reduce my concentration in ${c.top_holding_ticker}?`,
    });
  }
  if (c?.top_sector && topSector > 0.5) {
    levers.push({
      key: "sector",
      sev: topSector > 0.65 ? 3 : 2,
      title: `Diversify beyond ${c.top_sector}`,
      detail: `${c.top_sector} is ${pct0(topSector)} of your book — spreading across sectors lowers single-theme risk.`,
      q: `How do I diversify away from ${c.top_sector}?`,
    });
  }
  if (vol != null && targetVol && vol > targetVol * 1.15) {
    levers.push({
      key: "vol",
      sev: vol > targetVol * 1.5 ? 3 : 2,
      title: "Bring volatility toward your target",
      detail: `Your ${pct0(vol)} volatility is above your ${pct0(targetVol)} "${profile}" target — a bond or cash sleeve lowers it.`,
      q: "How can I lower my portfolio's volatility?",
    });
  }
  if (beta != null && targetBeta && beta > targetBeta * 1.2) {
    levers.push({
      key: "beta",
      sev: 1,
      title: "Reduce market sensitivity",
      detail: `Beta ${beta.toFixed(2)} vs your ${targetBeta.toFixed(2)} target — lower-beta or defensive names cut how hard the market drags you.`,
      q: "How do I lower my portfolio beta?",
    });
  }
  if (dd != null && dd < -0.3) {
    levers.push({
      key: "drawdown",
      sev: dd < -0.45 ? 3 : 2,
      title: "Add a downside cushion",
      detail: `A ${pct0(Math.abs(dd))} modelled drawdown is steep — a defensive sleeve (bonds, gold, cash) softens a selloff.`,
      q: "How can I protect against a big drawdown?",
    });
  }
  if (sharpe != null && sharpe < 0.5) {
    levers.push({
      key: "sharpe",
      sev: sharpe < 0 ? 2 : 1,
      title: "You're not paid for the risk",
      detail: `A Sharpe of ${sharpe.toFixed(2)} means the return hasn't justified the volatility — review whether the risk is earning its keep.`,
      q: "Why is my Sharpe ratio low and how do I improve it?",
    });
  }
  if (leverage != null && leverage > 1.05) {
    levers.push({
      key: "margin",
      sev: leverage > 1.5 ? 3 : 2,
      title: "Margin is amplifying your risk",
      detail: `${leverage.toFixed(2)}× leverage magnifies every move and adds borrow drag — a drawdown hits your equity harder.`,
      q: "How does my margin affect my risk?",
    });
  }
  if (score.options?.flags?.length) {
    levers.push({
      key: "options",
      sev: 2,
      title: "Review your option exposure",
      detail: `Your options carry risk flags (e.g. ${score.options.flags[0]}) — check coverage and collateral before they bite.`,
      q: "What are the risks in my current option positions?",
    });
  }

  return levers.sort((a, b) => b.sev - a.sev).slice(0, 3);
}

export function ImproveScore({ score }: { score: ScoreResponse }) {
  const levers = buildLevers(score);
  if (levers.length === 0) return null;

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">How to improve this score</CardTitle>
        <CardDescription>
          Biggest lever first — computed from your own numbers. Educational, not advice.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {levers.map((l, i) => (
          <div key={l.key} className="rounded-lg border border-border bg-muted/20 p-3">
            <div className="flex items-baseline gap-2">
              <span className="font-mono text-xs text-muted-foreground">{i + 1}</span>
              <p className="font-medium">{l.title}</p>
            </div>
            <p className="mt-1 text-sm text-muted-foreground">{l.detail}</p>
            <div className="mt-2 flex flex-wrap gap-3 text-sm">
              <Link
                href={`/copilot?q=${encodeURIComponent(l.q)}`}
                className="text-primary hover:underline"
              >
                Ask Copilot →
              </Link>
              <Link href="/portfolios" className="text-muted-foreground hover:underline">
                Edit holdings
              </Link>
              <a href="#whatif" className="text-muted-foreground hover:underline">
                Try it in the What-if lab
              </a>
            </div>
          </div>
        ))}
        <p className="text-xs text-muted-foreground">
          Educational — not a recommendation to buy or sell. Figures are your computed metrics.
        </p>
      </CardContent>
    </Card>
  );
}
