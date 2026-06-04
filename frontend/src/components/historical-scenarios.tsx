"use client";

/**
 * "How your ACTUAL holdings rode out real crises" — replays COVID / 2022 / 2018
 * / GFC on the user's portfolio (the /risk/historical_scenarios endpoint). Far
 * more visceral + credible than a synthetic −30%. Renders nothing if there are
 * no usable episodes (fail-soft).
 */

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import type { HistoricalScenarioRow, HistoricalScenarios } from "@/lib/queries";
import { cn } from "@/lib/utils";

function pct(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "—";
  const s = v >= 0 ? "+" : "";
  return `${s}${(v * 100).toFixed(1)}%`;
}
function tone(v: number | null | undefined): string {
  if (v == null) return "";
  return v >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400";
}

export function HistoricalScenarios({
  data,
  loading,
}: {
  data: HistoricalScenarios | undefined;
  loading: boolean;
}) {
  const rows = data?.scenarios ?? [];
  if (!loading && rows.length === 0) return null; // fail-soft

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">If history repeated</CardTitle>
        <CardDescription>
          How your current holdings would have ridden out real market crises —
          actual prices, your weights. Not a hypothetical shock.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3 p-4 sm:grid-cols-2">
        {loading && rows.length === 0 && (
          <>
            <Skeleton className="h-28" />
            <Skeleton className="h-28" />
          </>
        )}
        {rows.map((s) => (
          <Episode key={s.label} s={s} />
        ))}
      </CardContent>
    </Card>
  );
}

function Episode({ s }: { s: HistoricalScenarioRow }) {
  const recovered = s.recovery_days != null;
  return (
    <div className="rounded-lg border border-border bg-muted/20 p-3">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-sm font-medium">{s.label}</span>
        <span className="text-[11px] text-muted-foreground">
          {s.start} → {s.end}
        </span>
      </div>
      <div className="mt-2 flex items-baseline gap-2">
        <span className={cn("font-mono text-2xl", tone(s.portfolio_return))}>
          {pct(s.portfolio_return)}
        </span>
        <span className="text-xs text-muted-foreground">your portfolio</span>
      </div>
      <dl className="mt-2 space-y-0.5 text-xs text-muted-foreground">
        <Row label="S&P 500" value={pct(s.market_return)} />
        <Row label="Deepest drawdown" value={pct(s.max_drawdown)} />
        <Row
          label="Time to recover"
          value={recovered ? `~${s.recovery_days} trading days` : "had not recovered"}
        />
        {s.coverage != null && s.coverage < 0.95 && (
          <Row label="Coverage" value={`${(s.coverage * 100).toFixed(0)}% of holdings traded then`} />
        )}
      </dl>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-2">
      <dt>{label}</dt>
      <dd className="font-mono text-foreground">{value}</dd>
    </div>
  );
}
