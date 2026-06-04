"use client";

/**
 * Regime-analysis tab for /quant. Reuses the existing public
 * /macro/regime_detail data (no new endpoint) and adds a client-computed
 * regime transition matrix from the ~1y history — "once you're in regime X,
 * where do you tend to go next?".
 */

import { useMemo } from "react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useRegimeDetail, type RegimeDetail } from "@/lib/queries";
import { cn } from "@/lib/utils";

function regimeTone(regime: string | null | undefined): string {
  const r = (regime ?? "").toLowerCase();
  if (r.includes("bull")) return "text-emerald-600 dark:text-emerald-400";
  if (r.includes("bear")) return "text-red-600 dark:text-red-400";
  if (r.includes("trans")) return "text-amber-600 dark:text-amber-400";
  return "text-muted-foreground";
}

export function QuantRegime() {
  const q = useRegimeDetail();
  const d = q.data;

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        The market&apos;s statistical regime — bull, bear, or transition — from a
        composite of trend, volatility, and VIX, with how regimes have shifted
        over the past year.
      </p>

      {q.isLoading && <Skeleton className="h-40" />}
      {d && (
        <>
          <Card>
            <CardContent className="flex flex-wrap items-center justify-between gap-4 py-5">
              <div>
                <p className="text-xs uppercase tracking-widest text-muted-foreground">
                  Current regime
                </p>
                <p className={cn("text-3xl font-semibold", regimeTone(d.current_regime))}>
                  {d.current_regime ?? "Unknown"}
                </p>
                {d.regime_since_date && (
                  <p className="text-xs text-muted-foreground">since {d.regime_since_date}</p>
                )}
              </div>
              <div className="grid grid-cols-3 gap-3 text-sm">
                <SubSignal label="Trend" value={d.trend_regime} />
                <SubSignal label="Volatility" value={d.vol_regime} />
                <SubSignal label="VIX" value={d.vix_regime} />
              </div>
            </CardContent>
          </Card>

          <TransitionMatrix history={d.history} />
        </>
      )}
    </div>
  );
}

function SubSignal({ label, value }: { label: string; value: string | null }) {
  return (
    <div className="rounded-md border border-border bg-muted/20 p-2 text-center">
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className={cn("text-sm font-medium", regimeTone(value))}>{value ?? "—"}</div>
    </div>
  );
}

function TransitionMatrix({ history }: { history: RegimeDetail["history"] }) {
  const { regimes, matrix } = useMemo(() => buildMatrix(history), [history]);

  if (regimes.length === 0) {
    return (
      <Card>
        <CardContent className="py-6 text-sm text-muted-foreground">
          Not enough regime history to build a transition matrix yet.
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Regime transitions</CardTitle>
        <CardDescription>
          Day-to-day: once in the row regime, the chance of being in each column
          regime tomorrow (from the past year).
        </CardDescription>
      </CardHeader>
      <CardContent className="overflow-x-auto p-4">
        <table className="text-xs">
          <thead>
            <tr className="text-muted-foreground">
              <th className="px-2 py-1 text-left">from \ to</th>
              {regimes.map((r) => (
                <th key={r} className="px-2 py-1 text-center font-medium">
                  {r}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {regimes.map((from) => (
              <tr key={from}>
                <td className="px-2 py-1 font-medium">{from}</td>
                {regimes.map((to) => {
                  const p = matrix[from]?.[to] ?? 0;
                  return (
                    <td
                      key={to}
                      className="px-2 py-1 text-center font-mono"
                      style={{ backgroundColor: `hsl(var(--primary) / ${(p * 0.6).toFixed(3)})` }}
                    >
                      {(p * 100).toFixed(0)}%
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

/** Count adjacent transitions in the history and row-normalise to probabilities. */
function buildMatrix(history: RegimeDetail["history"]): {
  regimes: string[];
  matrix: Record<string, Record<string, number>>;
} {
  const seq = history.map((h) => h.regime).filter(Boolean);
  if (seq.length < 2) return { regimes: [], matrix: {} };

  const regimes = Array.from(new Set(seq)).sort();
  const counts: Record<string, Record<string, number>> = {};
  for (const a of regimes) counts[a] = Object.fromEntries(regimes.map((b) => [b, 0]));
  for (let i = 0; i < seq.length - 1; i++) counts[seq[i]][seq[i + 1]] += 1;

  const matrix: Record<string, Record<string, number>> = {};
  for (const from of regimes) {
    const total = regimes.reduce((s, to) => s + counts[from][to], 0);
    matrix[from] = Object.fromEntries(
      regimes.map((to) => [to, total > 0 ? counts[from][to] / total : 0]),
    );
  }
  return { regimes, matrix };
}
