"use client";

/**
 * "vs what?" — frames the user's own annualized stats against the S&P 500 and a
 * 60/40 blend (the public /risk/benchmarks endpoint). A lone metric is noise; a
 * metric next to its baseline is a judgement. Used on /score and /risk. Renders
 * nothing if the benchmark fetch is empty (fail-soft), so it never blocks.
 */

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useBenchmarks } from "@/lib/queries";
import { cn } from "@/lib/utils";

export type MyStats = {
  annual_return?: number | null;
  annual_volatility?: number | null;
  sharpe_ratio?: number | null;
  max_drawdown?: number | null;
};

const ROWS: { key: keyof MyStats; label: string; fmt: "pct" | "num"; higherBetter: boolean }[] = [
  { key: "annual_return", label: "Annualized return", fmt: "pct", higherBetter: true },
  { key: "annual_volatility", label: "Volatility", fmt: "pct", higherBetter: false },
  { key: "sharpe_ratio", label: "Sharpe", fmt: "num", higherBetter: true },
  { key: "max_drawdown", label: "Max drawdown", fmt: "pct", higherBetter: true }, // less-negative is better
];

function fmt(v: number | null | undefined, kind: "pct" | "num"): string {
  if (v == null || Number.isNaN(v)) return "—";
  return kind === "pct" ? `${(v * 100).toFixed(1)}%` : v.toFixed(2);
}

export function BenchmarkContext({ mine }: { mine: MyStats }) {
  const q = useBenchmarks();
  const benchmarks = q.data?.benchmarks ?? [];
  if (benchmarks.length === 0) return null; // fail-soft: no context, no card

  const cols = [{ name: "You", stats: mine as MyStats }, ...benchmarks.map((b) => ({ name: b.name, stats: b as MyStats }))];

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">How you compare</CardTitle>
        <CardDescription>
          Your portfolio vs common baselines over the trailing year
          {q.data?.as_of ? ` · as of ${q.data.as_of}` : ""}.
        </CardDescription>
      </CardHeader>
      <CardContent className="overflow-x-auto p-4">
        <table className="w-full min-w-[420px] text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs text-muted-foreground">
              <th className="py-2 pr-3 font-medium">Metric</th>
              {cols.map((c) => (
                <th key={c.name} className="px-3 py-2 text-right font-medium">
                  {c.name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ROWS.map((r) => {
              return (
                <tr key={r.key} className="border-b border-border/40">
                  <td className="py-2 pr-3 text-muted-foreground">{r.label}</td>
                  {cols.map((c, i) => {
                    const v = c.stats[r.key];
                    const isYou = i === 0;
                    // Tone "You" vs the S&P 500 (first benchmark) on this metric.
                    let tone = "";
                    if (isYou && benchmarks[0]) {
                      const bench = benchmarks[0][r.key];
                      if (v != null && bench != null) {
                        const better = r.higherBetter ? v >= bench : v <= bench;
                        tone = better
                          ? "text-emerald-600 dark:text-emerald-400"
                          : "text-amber-600 dark:text-amber-400";
                      }
                    }
                    return (
                      <td
                        key={c.name}
                        className={cn("px-3 py-2 text-right font-mono", isYou && "font-semibold", tone)}
                      >
                        {fmt(v, r.fmt)}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}
