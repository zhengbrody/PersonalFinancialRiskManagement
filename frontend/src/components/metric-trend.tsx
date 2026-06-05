"use client";

/**
 * A compact trend sparkline of one snapshot metric over time (Health score,
 * volatility, VaR…). This is the retention hook: a point value is a fact, a
 * trend is a relationship the user comes back to watch. Self-fetching (React
 * Query dedupes if several render at once). Renders nothing until there are at
 * least two snapshots — we save one each time the user scores.
 */

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { TimeSeriesChart } from "@/components/ui/chart-line";
import { useSnapshotHistory, type SnapshotPoint } from "@/lib/queries";

type Kind = "score" | "pct" | "usd";

export function MetricTrend({
  metric,
  title,
  description,
  kind,
}: {
  metric: keyof SnapshotPoint;
  title: string;
  description?: string;
  kind: Kind;
}) {
  const q = useSnapshotHistory();
  const points = (q.data?.snapshots ?? [])
    .map((s) => ({ date: String(s.as_of ?? ""), value: s[metric] as number | null }))
    .filter((p): p is { date: string; value: number } => p.value != null && p.date !== "");

  if (q.isLoading) return <Skeleton className="h-40" />;
  if (points.length < 2) return null; // not enough history yet — stay quiet

  const fmt =
    kind === "score"
      ? (v: number) => String(Math.round(v))
      : kind === "usd"
        ? (v: number) => `$${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}`
        : (v: number) => `${(v * 100).toFixed(1)}%`;

  // Snapshots are days apart → label by month+day (e.g. "May 28"), not the
  // chart's default month+year ("May 26" = May 2026, which looked like a day).
  const fmtDay = (iso: string) => {
    const d = new Date(iso);
    return Number.isNaN(d.getTime())
      ? iso
      : d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  };

  return (
    <Card>
      <CardHeader className="pb-1">
        <CardTitle className="text-base">{title}</CardTitle>
        {description && <CardDescription>{description}</CardDescription>}
      </CardHeader>
      <CardContent className="p-4 pt-2">
        <TimeSeriesChart
          data={points}
          variant="line"
          height={160}
          valueFormatter={fmt}
          dateFormatter={fmtDay}
          ariaLabel={title}
        />
      </CardContent>
    </Card>
  );
}
