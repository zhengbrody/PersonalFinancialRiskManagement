"use client";

/**
 * Deterministic peer comparison (Phase 2). Median, percentiles, and every metric
 * come from the backend; this component only sorts/plots them. Educational only.
 */

import { useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  Cell,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { usePeers, type PeerRow, type PeersOutput } from "@/lib/queries";

const pct = (v: number | null | undefined, d = 1) =>
  v == null || !Number.isFinite(v) ? "—" : `${(v * 100).toFixed(d)}%`;
const x = (v: number | null | undefined, d = 1) =>
  v == null || !Number.isFinite(v) ? "—" : `${v.toFixed(d)}×`;
const cap = (v: number | null | undefined) => {
  if (v == null || !Number.isFinite(v)) return "—";
  if (v >= 1e12) return `$${(v / 1e12).toFixed(2)}T`;
  if (v >= 1e9) return `$${(v / 1e9).toFixed(0)}B`;
  return `$${(v / 1e6).toFixed(0)}M`;
};

type Col = {
  key: keyof PeerRow;
  label: string;
  fmt: (v: number | null | undefined) => string;
};
const COLS: Col[] = [
  { key: "market_cap", label: "Mkt cap", fmt: cap },
  { key: "revenue_growth", label: "Rev gr", fmt: (v) => pct(v) },
  { key: "gross_margin", label: "Gross", fmt: (v) => pct(v) },
  { key: "operating_margin", label: "Op", fmt: (v) => pct(v) },
  { key: "net_margin", label: "Net", fmt: (v) => pct(v) },
  { key: "fcf_margin", label: "FCF", fmt: (v) => pct(v) },
  { key: "roe", label: "ROE", fmt: (v) => pct(v) },
  { key: "pe", label: "P/E", fmt: (v) => x(v) },
  { key: "forward_pe", label: "Fwd P/E", fmt: (v) => x(v) },
  { key: "ev_sales", label: "EV/S", fmt: (v) => x(v) },
  { key: "ev_ebitda", label: "EV/EBITDA", fmt: (v) => x(v) },
  { key: "ps", label: "P/S", fmt: (v) => x(v) },
  { key: "debt_to_equity", label: "D/E", fmt: (v) => x(v, 2) },
];

const BADGE_METRICS = [
  { metric: "revenue_growth", label: "Revenue growth", fmt: (v: number | null) => pct(v) },
  { metric: "operating_margin", label: "Operating margin", fmt: (v: number | null) => pct(v) },
  { metric: "net_margin", label: "Net margin", fmt: (v: number | null) => pct(v) },
  { metric: "pe", label: "P/E", fmt: (v: number | null) => x(v) },
];

export function PeersComparison({
  ticker,
  data,
}: {
  ticker: string | null;
  data?: PeersOutput;
}) {
  const q = usePeers(data ? null : ticker);
  if (!ticker && !data) return null;
  if (!data) {
    if (q.isLoading) return <PeersSkeleton />;
    if (q.isError || !q.data) {
      return (
        <Card>
          <CardContent className="py-6 text-sm text-muted-foreground">
            Couldn&apos;t load peers right now — please try again shortly.
          </CardContent>
        </Card>
      );
    }
  }
  const out = data ?? q.data!.peers;
  return (
    <div className="space-y-4">
      <PercentileBadges out={out} />
      <PeerTable out={out} />
      <ValuationScatter out={out} />
      <div className="grid gap-4 lg:grid-cols-2">
        <MetricBars out={out} metric="revenue_growth" title="Revenue growth vs peers" asPct />
        <MetricBars out={out} metric="operating_margin" title="Operating margin vs peers" asPct />
        <MetricBars out={out} metric="ev_sales" title="EV/Sales vs peers" />
        <MetricBars out={out} metric="pe" title="P/E vs peers" />
      </div>
      <p className="text-[11px] leading-relaxed text-muted-foreground">{out.disclaimer}</p>
    </div>
  );
}

function PercentileBadges({ out }: { out: PeersOutput }) {
  const byMetric = Object.fromEntries(out.percentiles.map((p) => [p.metric, p]));
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">
          Where {out.ticker} ranks{" "}
          <span className="text-sm font-normal text-muted-foreground">
            (peer source: {out.peer_source})
          </span>
        </CardTitle>
        <CardDescription>Percentile among the peer set (higher = larger value).</CardDescription>
      </CardHeader>
      <CardContent className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {BADGE_METRICS.map((b) => {
          const p = byMetric[b.metric];
          const rank = p?.percentile;
          return (
            <div key={b.metric}>
              <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{b.label}</p>
              <p className="font-mono text-sm font-semibold">{b.fmt(p?.subject_value ?? null)}</p>
              <p className="text-[11px] text-muted-foreground">
                median {b.fmt(p?.peer_median ?? null)}
                {rank != null && (
                  <span className="ml-1 rounded bg-sky-500/15 px-1 py-px text-sky-700 dark:text-sky-300">
                    {Math.round(rank * 100)}th
                  </span>
                )}
              </p>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}

function PeerTable({ out }: { out: PeersOutput }) {
  const [sort, setSort] = useState<{ key: keyof PeerRow; dir: 1 | -1 }>({
    key: "market_cap",
    dir: -1,
  });
  const rows = useMemo(() => {
    const arr = [...out.rows];
    arr.sort((a, b) => {
      const av = a[sort.key] as number | null;
      const bv = b[sort.key] as number | null;
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      return (av - bv) * sort.dir;
    });
    return arr;
  }, [out.rows, sort]);

  const toggle = (key: keyof PeerRow) =>
    setSort((s) => (s.key === key ? { key, dir: (s.dir * -1) as 1 | -1 } : { key, dir: -1 }));

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Peer table</CardTitle>
        <CardDescription>Click a column to sort · subject row highlighted.</CardDescription>
      </CardHeader>
      <CardContent className="overflow-x-auto">
        <table className="w-full min-w-[760px] text-right text-xs tabular-nums">
          <thead>
            <tr className="border-b border-border text-[10px] uppercase tracking-wide text-muted-foreground">
              <th className="py-1.5 text-left">Ticker</th>
              {COLS.map((c) => (
                <th
                  key={c.key}
                  className="cursor-pointer select-none px-1 font-medium hover:text-foreground"
                  onClick={() => toggle(c.key)}
                >
                  {c.label}
                  {sort.key === c.key ? (sort.dir === -1 ? " ↓" : " ↑") : ""}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr
                key={r.ticker}
                className={`border-b border-border/40 ${r.is_subject ? "bg-primary/10 font-semibold" : ""}`}
              >
                <td className="py-1.5 text-left">{r.ticker}</td>
                {COLS.map((c) => (
                  <td key={c.key} className="px-1">
                    {c.fmt(r[c.key] as number | null)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

function ValuationScatter({ out }: { out: PeersOutput }) {
  const data = out.rows
    .filter((r) => r.revenue_growth != null && r.ev_sales != null)
    .map((r) => ({
      ticker: r.ticker,
      x: (r.revenue_growth as number) * 100,
      y: r.ev_sales as number,
      subject: r.is_subject,
    }));
  if (data.length < 2) return null;
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Growth vs valuation</CardTitle>
        <CardDescription>Revenue growth (x) vs EV/Sales (y) — subject highlighted.</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="h-64 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <ScatterChart margin={{ top: 8, right: 12, bottom: 16, left: -6 }}>
              <XAxis
                type="number"
                dataKey="x"
                name="Rev growth %"
                unit="%"
                tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
              />
              <YAxis
                type="number"
                dataKey="y"
                name="EV/Sales"
                tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
              />
              <ZAxis range={[60, 60]} />
              <Tooltip
                cursor={{ strokeDasharray: "3 3" }}
                contentStyle={{
                  background: "hsl(var(--card))",
                  border: "1px solid hsl(var(--border))",
                  borderRadius: 8,
                  fontSize: 12,
                }}
                formatter={(value, name) => {
                  const v = Number(value);
                  return [name === "y" ? `${v.toFixed(1)}×` : `${v.toFixed(1)}%`, name === "y" ? "EV/S" : "Rev gr"];
                }}
                labelFormatter={() => ""}
              />
              <Scatter data={data}>
                {data.map((d) => (
                  <Cell key={d.ticker} fill={d.subject ? "hsl(var(--primary))" : "hsl(var(--muted-foreground))"} />
                ))}
              </Scatter>
            </ScatterChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  );
}

function MetricBars({
  out,
  metric,
  title,
  asPct,
}: {
  out: PeersOutput;
  metric: keyof PeerRow;
  title: string;
  asPct?: boolean;
}) {
  const data = out.rows
    .filter((r) => r[metric] != null)
    .map((r) => ({
      ticker: r.ticker,
      v: asPct ? (r[metric] as number) * 100 : (r[metric] as number),
      subject: r.is_subject,
    }));
  if (data.length < 2) return null;
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="h-44 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: -10 }}>
              <XAxis dataKey="ticker" tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }} />
              <YAxis tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }} unit={asPct ? "%" : ""} />
              <Tooltip
                contentStyle={{
                  background: "hsl(var(--card))",
                  border: "1px solid hsl(var(--border))",
                  borderRadius: 8,
                  fontSize: 12,
                }}
                formatter={(value) => {
                  const v = Number(value);
                  return [asPct ? `${v.toFixed(1)}%` : `${v.toFixed(1)}×`, ""];
                }}
              />
              <Bar dataKey="v" radius={[3, 3, 0, 0]}>
                {data.map((d) => (
                  <Cell key={d.ticker} fill={d.subject ? "hsl(var(--primary))" : "hsl(var(--muted-foreground))"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  );
}

function PeersSkeleton() {
  return (
    <Card>
      <CardContent className="space-y-3 py-6">
        <Skeleton className="h-5 w-40" />
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-40 w-full" />
      </CardContent>
    </Card>
  );
}
