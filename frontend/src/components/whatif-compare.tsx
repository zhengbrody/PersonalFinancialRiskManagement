"use client";

/**
 * What-if lab — Before → After strip. Pure presentation over two score
 * responses the page already holds (your saved book vs the sandbox mix);
 * nothing is recomputed here and nothing is saved. Green/red follows each
 * metric's OWN goodness direction (lower vol is good, higher Sharpe is good,
 * beta has no universal direction → neutral).
 */

import { Button } from "@/components/ui/button";
import type { ScoreResponse } from "@/lib/schemas";

type Direction = "higher" | "lower" | "neutral";

type MetricSpec = {
  label: string;
  read: (s: ScoreResponse) => number | null | undefined;
  fmt: (v: number) => string;
  direction: Direction;
};

const pct = (v: number) => `${(v * 100).toFixed(1)}%`;

const METRICS: MetricSpec[] = [
  { label: "Health Score", read: (s) => s.overall_score, fmt: (v) => v.toFixed(0), direction: "higher" },
  { label: "年化波动", read: (s) => s.metrics.annual_volatility, fmt: pct, direction: "lower" },
  { label: "VaR 95 (1d)", read: (s) => s.metrics.var_95_daily, fmt: pct, direction: "lower" },
  { label: "Sharpe", read: (s) => s.metrics.sharpe_ratio, fmt: (v) => v.toFixed(2), direction: "higher" },
  { label: "β", read: (s) => s.metrics.beta_to_benchmark, fmt: (v) => v.toFixed(2), direction: "neutral" },
  {
    label: "最大单一持仓",
    read: (s) => s.concentration?.top_holding_weight,
    fmt: pct,
    direction: "lower",
  },
];

function deltaTone(delta: number, direction: Direction): string {
  if (direction === "neutral" || delta === 0) return "text-muted-foreground";
  const good = direction === "higher" ? delta > 0 : delta < 0;
  return good ? "text-[hsl(var(--success))]" : "text-destructive";
}

export function WhatIfCompare({
  baseline,
  sandbox,
  onReset,
}: {
  baseline: ScoreResponse;
  sandbox: ScoreResponse;
  onReset: () => void;
}) {
  return (
    <div
      data-testid="whatif-compare"
      className="space-y-3 rounded-xl border border-primary/40 bg-primary/5 p-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-semibold">
          调仓沙盘结果 <span className="font-normal text-muted-foreground">vs 你的真实账本</span>
        </p>
        <Button variant="outline" size="sm" onClick={onReset}>
          返回真实账本
        </Button>
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        {METRICS.map((m) => {
          const before = m.read(baseline);
          const after = m.read(sandbox);
          if (before == null || after == null) {
            return (
              <div key={m.label} className="rounded-lg border border-border bg-background/50 p-2.5">
                <p className="text-[10px] uppercase tracking-widest text-muted-foreground">{m.label}</p>
                <p className="mt-1 font-mono text-sm tabular-nums">—</p>
              </div>
            );
          }
          const delta = after - before;
          return (
            <div key={m.label} className="rounded-lg border border-border bg-background/50 p-2.5">
              <p className="text-[10px] uppercase tracking-widest text-muted-foreground">{m.label}</p>
              <p className="mt-1 font-mono text-sm tabular-nums">
                <span className="text-muted-foreground">{m.fmt(before)}</span>
                <span className="mx-1 text-muted-foreground">→</span>
                <span className="font-semibold">{m.fmt(after)}</span>
              </p>
              <p className={`font-mono text-[11px] tabular-nums ${deltaTone(delta, m.direction)}`}>
                {delta >= 0 ? "+" : ""}
                {m.label === "Health Score" ? delta.toFixed(0) : m.fmt(delta)}
              </p>
            </div>
          );
        })}
      </div>

      <p className="text-[11px] text-muted-foreground">
        下方驾驶舱当前显示的是沙盘账本的完整分析。沙盘不会保存、不改动你的持仓,也不构成投资建议
        — 只是同一个确定性引擎对另一组数字的重算。
      </p>
    </div>
  );
}
