"use client";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useSnapshotHistory } from "@/lib/queries";

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
  description = "Account-level value, today's move, and return history.",
}: {
  metrics: PortfolioValueMetrics;
  title?: string;
  description?: string;
}) {
  const history = useSnapshotHistory();
  const currentValue = finite(metrics.net_equity) ?? finite(metrics.total_value);
  const first = (history.data?.snapshots ?? []).find((s) => finite(s.net_equity) != null);
  const firstValue = finite(first?.net_equity);
  const historyPnl =
    currentValue != null && firstValue != null ? currentValue - firstValue : null;
  const historyReturn =
    historyPnl != null && firstValue != null && firstValue > 0
      ? historyPnl / firstValue
      : null;

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <ValueTile label="Net equity" value={fmtUSD(currentValue)} />
        <ValueTile
          label="Today"
          value={fmtSignedUSD(metrics.daily_pnl)}
          delta={fmtSignedPct(metrics.daily_return)}
          tone={tone(metrics.daily_pnl)}
          muted="Needs two recent closes"
        />
        <ValueTile
          label="Total return"
          value={fmtSignedUSD(metrics.total_pnl)}
          delta={fmtSignedPct(metrics.total_return)}
          tone={tone(metrics.total_pnl)}
          muted="Add contributed capital"
        />
        <ValueTile
          label={first?.as_of ? `Since ${fmtDate(first.as_of)}` : "History change"}
          value={fmtSignedUSD(historyPnl)}
          delta={fmtSignedPct(historyReturn)}
          tone={tone(historyPnl)}
          muted={history.isLoading ? "Loading history" : "Builds after snapshots"}
        />
      </CardContent>
    </Card>
  );
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
      ) : (
        muted && <p className="mt-0.5 text-xs text-muted-foreground">{muted}</p>
      )}
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
