"use client";

/**
 * Deterministic earnings comparison (Phase 3). Quarter actuals vs prior-quarter /
 * prior-year, beat/miss ONLY when an estimate exists, transcript availability, and
 * explicit missing states. Every number is from the backend. Educational only.
 */

import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useEarnings, type EarningsOutput } from "@/lib/queries";

const usd = (v: number | null | undefined) => {
  if (v == null || !Number.isFinite(v)) return "—";
  const a = Math.abs(v);
  if (a >= 1e12) return `$${(v / 1e12).toFixed(2)}T`;
  if (a >= 1e9) return `$${(v / 1e9).toFixed(1)}B`;
  if (a >= 1e6) return `$${(v / 1e6).toFixed(0)}M`;
  return `$${v.toFixed(2)}`;
};
const sp = (v: number | null | undefined) =>
  v == null || !Number.isFinite(v) ? "—" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;
const num = (v: number | null | undefined) =>
  v == null || !Number.isFinite(v) ? "—" : v.toFixed(2);

export function EarningsComparison({
  ticker,
  data,
}: {
  ticker: string | null;
  data?: EarningsOutput;
}) {
  const q = useEarnings(data ? null : ticker);
  if (!ticker && !data) return null;
  if (!data) {
    if (q.isLoading) return <EarnSkeleton />;
    if (q.isError || !q.data) {
      return (
        <Card>
          <CardContent className="py-6 text-sm text-muted-foreground">
            Couldn&apos;t load earnings right now — please try again shortly.
          </CardContent>
        </Card>
      );
    }
  }
  const e = data ?? q.data!.earnings;
  return (
    <div className="space-y-4">
      <Timeline e={e} />
      <QuarterTable e={e} />
      <Transcript e={e} />
      {e.missing_data.length > 0 && <Missing e={e} />}
      <p className="text-xs leading-relaxed text-muted-foreground">{e.disclaimer}</p>
    </div>
  );
}

function Timeline({ e }: { e: EarningsOutput }) {
  const data = e.periods
    .filter((p) => p.revenue != null)
    .slice()
    .reverse()
    .map((p) => ({ period: p.period, rev: Math.round((p.revenue as number) / 1e9), beat: p.revenue_beat }));
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Earnings timeline</CardTitle>
        <CardDescription>
          {e.summary.headline ?? "Quarterly revenue ($B)"} · oldest → newest
        </CardDescription>
      </CardHeader>
      <CardContent>
        {data.length >= 2 ? (
          <div className="h-44 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: -8 }}>
                <XAxis dataKey="period" tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }} />
                <YAxis tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }} />
                <Tooltip
                  contentStyle={{
                    background: "hsl(var(--card))",
                    border: "1px solid hsl(var(--border))",
                    borderRadius: 8,
                    fontSize: 12,
                  }}
                  formatter={(value) => [`$${Number(value)}B`, "Revenue"]}
                />
                <Bar dataKey="rev" radius={[3, 3, 0, 0]}>
                  {data.map((d, i) => (
                    <Cell
                      key={i}
                      fill={
                        d.beat === true
                          ? "#16a34a"
                          : d.beat === false
                            ? "#dc2626"
                            : "hsl(var(--primary))"
                      }
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <p className="py-4 text-sm text-muted-foreground">Not enough quarters to chart.</p>
        )}
      </CardContent>
    </Card>
  );
}

function Beat({ beat }: { beat: boolean | null | undefined }) {
  if (beat == null) return <span className="text-muted-foreground">—</span>;
  return (
    <span
      className={`rounded px-1.5 py-px text-[10px] font-semibold ${beat ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300" : "bg-red-500/15 text-red-700 dark:text-red-300"}`}
    >
      {beat ? "Beat" : "Miss"}
    </span>
  );
}

function QuarterTable({ e }: { e: EarningsOutput }) {
  if (e.periods.length === 0) {
    return (
      <Card>
        <CardContent className="py-6 text-sm text-muted-foreground">
          No quarterly earnings data available.
        </CardContent>
      </Card>
    );
  }
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Quarter comparison</CardTitle>
        <CardDescription>Beat/miss shown only where an estimate exists.</CardDescription>
      </CardHeader>
      <CardContent className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-right text-sm tabular-nums">
          <thead>
            <tr className="border-b border-border text-[10px] uppercase tracking-wide text-muted-foreground">
              <th className="py-1.5 text-left">Period</th>
              <th>Revenue</th>
              <th>Rev YoY</th>
              <th>Rev QoQ</th>
              <th>Rev vs est</th>
              <th>EPS</th>
              <th>EPS YoY</th>
              <th>EPS vs est</th>
            </tr>
          </thead>
          <tbody>
            {e.periods.map((p) => (
              <tr key={p.period} className="border-b border-border/40">
                <td className="py-1.5 text-left font-medium">{p.period}</td>
                <td>{usd(p.revenue)}</td>
                <td>{sp(p.revenue_yoy)}</td>
                <td>{sp(p.revenue_qoq)}</td>
                <td>
                  <Beat beat={p.revenue_beat} />
                </td>
                <td>{num(p.eps)}</td>
                <td>{sp(p.eps_yoy)}</td>
                <td>
                  <Beat beat={p.eps_beat} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

function Transcript({ e }: { e: EarningsOutput }) {
  const t = e.transcript;
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Earnings call transcript</CardTitle>
      </CardHeader>
      <CardContent className="text-sm">
        {t.available ? (
          <p>
            Latest transcript available
            {t.fiscal_year ? ` — FY${t.fiscal_year} Q${t.quarter}` : ""}
            {t.date ? `, ${t.date}` : ""} ({t.source}). The AI thesis (Overview tab) summarizes
            management tone &amp; guidance from it.
          </p>
        ) : (
          <p className="text-muted-foreground">
            No transcript available for this ticker (or not included in the current data plan).
            Earnings comparisons above are unaffected.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function Missing({ e }: { e: EarningsOutput }) {
  return (
    <div className="rounded-md bg-amber-500/10 px-3 py-2">
      <p className="text-[11px] font-medium uppercase tracking-wide text-amber-700 dark:text-amber-300">
        Missing data
      </p>
      <ul className="mt-1 space-y-0.5 text-xs text-muted-foreground">
        {e.missing_data.map((m) => (
          <li key={`${m.dataset}:${m.reason}`}>
            {m.dataset} — {m.reason.replace(/_/g, " ")}
          </li>
        ))}
      </ul>
    </div>
  );
}

function EarnSkeleton() {
  return (
    <Card>
      <CardContent className="space-y-3 py-6">
        <Skeleton className="h-5 w-40" />
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-32 w-full" />
      </CardContent>
    </Card>
  );
}
