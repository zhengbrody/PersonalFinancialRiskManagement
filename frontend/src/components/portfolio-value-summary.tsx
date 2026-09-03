"use client";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { type SnapshotPoint, useSnapshotHistory } from "@/lib/queries";

export type PortfolioValueMetrics = {
  total_value?: number | null;
  net_equity?: number | null;
  cash_balance?: number | null;
  margin_loan?: number | null;
  contributed_capital?: number | null;
  daily_pnl?: number | null;
  daily_return?: number | null;
  total_pnl?: number | null;
  total_return?: number | null;
};

export function PortfolioValueSummary({
  metrics,
  title = "Portfolio value",
  description = "Account value, net-contribution return, and cash-flow-adjusted history.",
}: {
  metrics: PortfolioValueMetrics;
  title?: string;
  description?: string;
}) {
  const history = useSnapshotHistory();
  const currentValue = finite(metrics.net_equity) ?? finite(metrics.total_value);
  const performance = cashAdjustedPerformance(
    history.data?.snapshots ?? [],
    currentValue,
    finite(metrics.contributed_capital),
  );
  const first = performance.first;

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <ValueTile label="Net equity" value={fmtUSD(currentValue)} />
          <ValueTile
            label="Today (priced holdings)"
            value={fmtSignedUSD(metrics.daily_pnl)}
            delta={fmtSignedPct(metrics.daily_return)}
            tone={tone(metrics.daily_pnl)}
            muted="Options need prior marks for daily P&L"
          />
          <ValueTile
            label="Since net contributions"
            value={fmtSignedUSD(metrics.total_pnl)}
            delta={fmtSignedPct(metrics.total_return)}
            tone={tone(metrics.total_pnl)}
            muted="Set total net contributed capital"
          />
          <ValueTile
            label={
              first?.as_of
                ? `${performance.flowAdjusted ? "Cash-adjusted" : "Value change"} since ${fmtDate(first.as_of)}`
                : "Tracked performance"
            }
            value={fmtSignedUSD(performance.pnl)}
            delta={fmtSignedPct(performance.returnPct)}
            tone={tone(performance.pnl)}
            muted={
              history.isLoading
                ? "Loading history"
                : performance.flowAdjusted && performance.netFlows !== 0
                  ? `${fmtSignedUSD(performance.netFlows)} net flows removed`
                  : "Builds after snapshots"
            }
          />
        </div>
        <p className="text-[11px] text-muted-foreground">
          “Annualized return” in the risk model describes the current holdings&apos; historical
          price behavior. It is not broker YTD. MindMarket labels YTD only when a Jan 1 value
          anchor and dated external cash flows are available.
        </p>
      </CardContent>
    </Card>
  );
}

type CashAdjustedPerformance = {
  first: SnapshotPoint | undefined;
  pnl: number | null;
  returnPct: number | null;
  netFlows: number;
  flowAdjusted: boolean;
};

/** Modified-Dietz-style return inferred from contribution changes in snapshots. */
export function cashAdjustedPerformance(
  snapshots: SnapshotPoint[],
  currentValue: number | null,
  currentContributed: number | null,
  now = new Date(),
): CashAdjustedPerformance {
  const usable = snapshots.filter((snapshot) => finite(snapshot.net_equity) != null);
  const first = usable[0];
  const firstValue = finite(first?.net_equity);
  if (!first || firstValue == null || currentValue == null) {
    return { first, pnl: null, returnPct: null, netFlows: 0, flowAdjusted: false };
  }

  const firstCapital = finite(first.contributed_capital);
  if (firstCapital == null || currentContributed == null) {
    const pnl = currentValue - firstValue;
    return {
      first,
      pnl,
      returnPct: firstValue > 0 ? pnl / firstValue : null,
      netFlows: 0,
      flowAdjusted: false,
    };
  }

  const startMs = parsedMs(first.as_of) ?? now.getTime();
  const endMs = Math.max(now.getTime(), startMs + 1);
  let previousCapital = firstCapital;
  let weightedFlows = 0;
  for (const snapshot of usable.slice(1)) {
    const capital = finite(snapshot.contributed_capital);
    if (capital == null) continue;
    const flow = capital - previousCapital;
    if (flow !== 0) {
      const flowMs = Math.min(endMs, Math.max(startMs, parsedMs(snapshot.as_of) ?? endMs));
      weightedFlows += flow * ((endMs - flowMs) / (endMs - startMs));
    }
    previousCapital = capital;
  }

  // A change after the newest snapshot has unknown timing. It still adjusts
  // dollar P&L, but receives zero time weight rather than an invented date.
  const netFlows = currentContributed - firstCapital;
  const pnl = currentValue - firstValue - netFlows;
  const denominator = firstValue + weightedFlows;
  return {
    first,
    pnl,
    returnPct: denominator > 0 ? pnl / denominator : null,
    netFlows,
    flowAdjusted: true,
  };
}

function parsedMs(value: string | null | undefined): number | null {
  if (!value) return null;
  const ms = new Date(value).getTime();
  return Number.isFinite(ms) ? ms : null;
}

function ValueTile({
  label,
  value,
  delta,
  tone: toneClass,
  muted,
}: {
  label: string;
  value: string;
  delta?: string;
  tone?: string;
  muted?: string;
}) {
  const empty = value === "—";
  return (
    <div className="rounded-md border border-border bg-muted/20 p-3">
      <p className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className={`mt-1 font-mono text-xl ${!empty ? toneClass ?? "" : ""}`}>{value}</p>
      {delta && delta !== "—" ? (
        <p className={`mt-0.5 font-mono text-xs ${toneClass ?? ""}`}>{delta}</p>
      ) : null}
      {muted && <p className="mt-0.5 text-xs text-muted-foreground">{muted}</p>}
    </div>
  );
}

function finite(v: number | null | undefined): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function tone(v: number | null | undefined): string {
  const n = finite(v);
  if (n == null || n === 0) return "text-muted-foreground";
  return n > 0
    ? "text-emerald-600 dark:text-emerald-400"
    : "text-red-600 dark:text-red-400";
}

function fmtUSD(v: number | null | undefined): string {
  const n = finite(v);
  if (n == null) return "—";
  return `$${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function fmtSignedUSD(v: number | null | undefined): string {
  const n = finite(v);
  if (n == null) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n < 0 ? "-" : ""}$${Math.abs(n).toLocaleString(undefined, {
    maximumFractionDigits: 0,
  })}`;
}

function fmtSignedPct(v: number | null | undefined): string {
  const n = finite(v);
  if (n == null) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${(n * 100).toFixed(2)}%`;
}

function fmtDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "tracking began";
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
