"use client";

/**
 * The three Portfolio-Health dimensions as interactive driver cards
 * (Risk Match · Risk-Adjusted Return · Downside Protection). Each shows the
 * dimension's 0–10 score + status, the top 1–2 numeric reasons (pure display
 * of metrics the score already returned — no computation), and a "Why?"
 * expander with the engine's own explanation.
 */

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { HorizontalBarChart, type BarDatum } from "@/components/ui/bar-chart";
import type { ScoreResponse } from "@/lib/schemas";
import { cn } from "@/lib/utils";

// Which already-computed metrics best explain each dimension. Order = render
// order; we show the first two that have a value.
const REASONS: Record<
  string,
  { label: string; key: keyof ScoreResponse["metrics"]; fmt: "pct" | "num" }[]
> = {
  risk_match: [
    { label: "Beta to market", key: "beta_to_benchmark", fmt: "num" },
    { label: "Annual volatility", key: "annual_volatility", fmt: "pct" },
  ],
  risk_adjusted_return: [
    { label: "Sharpe ratio", key: "sharpe_ratio", fmt: "num" },
    { label: "Annual return", key: "annual_return", fmt: "pct" },
  ],
  downside_protection: [
    { label: "Max drawdown", key: "max_drawdown", fmt: "pct" },
    { label: "CVaR 95 (daily)", key: "cvar_95_daily", fmt: "pct" },
  ],
};

const ORDER = ["risk_match", "risk_adjusted_return", "downside_protection"];

export function ScoreDrivers({ score }: { score: ScoreResponse }) {
  const keys = [
    ...ORDER.filter((k) => k in score.dimensions),
    ...Object.keys(score.dimensions).filter((k) => !ORDER.includes(k)),
  ];

  // Dimension scores (0–10) as bars — the lowest bar is the score's weakest
  // link, visible at a glance. Pure display of returned scores, red when ≤3.5
  // (the backend's weak-dimension threshold).
  const bars: BarDatum[] = keys.map((k) => {
    const d = score.dimensions[k];
    return {
      label: d.name,
      value: Number(d.score.toFixed(1)),
      color: d.score <= 3.5 ? "hsl(var(--destructive))" : "hsl(var(--primary))",
    };
  });

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-1">
          <CardTitle className="text-base">Score composition</CardTitle>
          <CardDescription>
            Each dimension out of 10 — the shortest bar is dragging your score
            down the most.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <HorizontalBarChart
            data={bars}
            valueFormatter={(v) => v.toFixed(1)}
            ariaLabel="Health dimensions out of 10"
          />
        </CardContent>
      </Card>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {keys.map((key) => (
          <DriverCard key={key} dimKey={key} score={score} />
        ))}
      </div>
    </div>
  );
}

function DriverCard({ dimKey, score }: { dimKey: string; score: ScoreResponse }) {
  const dim = score.dimensions[dimKey];
  const reasons = (REASONS[dimKey] ?? [])
    .map((r) => ({
      label: r.label,
      value: fmt(score.metrics[r.key] as number | null | undefined, r.fmt),
    }))
    .filter((r) => r.value !== "—")
    .slice(0, 2);

  return (
    <Card className="flex flex-col">
      <CardHeader className="pb-2">
        <CardDescription>{dim.name}</CardDescription>
        <CardTitle className="flex items-baseline gap-1.5 text-2xl">
          {dim.score.toFixed(1)}
          <span className="text-sm font-normal text-muted-foreground">/ 10</span>
        </CardTitle>
        <span className={cn("text-xs font-medium", statusTone(dim.status))}>
          {dim.status}
        </span>
      </CardHeader>
      <CardContent className="flex grow flex-col gap-3">
        {reasons.length > 0 && (
          <dl className="space-y-1 text-sm">
            {reasons.map((r) => (
              <div key={r.label} className="flex justify-between gap-2">
                <dt className="text-muted-foreground">{r.label}</dt>
                <dd className="font-mono">{r.value}</dd>
              </div>
            ))}
          </dl>
        )}
        {dim.detail && (
          <details className="mt-auto text-sm">
            <summary className="cursor-pointer text-primary hover:underline">
              Why?
            </summary>
            <p className="mt-1.5 text-muted-foreground">{dim.detail}</p>
          </details>
        )}
      </CardContent>
    </Card>
  );
}

function statusTone(status: string): string {
  const s = status.toLowerCase();
  if (/(strong|good|healthy|excellent|low)/.test(s))
    return "text-emerald-600 dark:text-emerald-400";
  if (/(weak|poor|high|critical|at risk|elevated)/.test(s))
    return "text-red-600 dark:text-red-400";
  if (/(watch|moderate|fair|ok)/.test(s)) return "text-amber-600 dark:text-amber-400";
  return "text-muted-foreground";
}

function fmt(v: number | null | undefined, kind: "pct" | "num"): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return kind === "pct" ? `${(v * 100).toFixed(2)}%` : v.toFixed(2);
}
