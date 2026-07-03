"use client";

/**
 * Rolling realized volatility — the desk's "is the book running hot vs its
 * own normal?" view. Two lines: the portfolio's 21-day rolling annualized
 * vol (leverage-adjusted, matches the levered book) and SPY's, unadjusted.
 * All values are backend-computed; the state chip is the backend's
 * deterministic calm/normal/elevated classification.
 *
 * NOTE the headline "Annual vol" KPI is EWMA-based (reacts faster to recent
 * shocks); this chart is the equal-weight 21-day window — both are standard
 * estimators and the caption says which is which.
 */

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { RollingVolatility } from "@/lib/queries";

const AXIS_COLOR = "hsl(var(--muted-foreground))";
const GRID_COLOR = "hsl(var(--border))";

const STATE_STYLE: Record<string, { label: string; className: string }> = {
  calm: { label: "Calm", className: "border-[hsl(var(--success))]/40 text-[hsl(var(--success))]" },
  normal: { label: "Normal", className: "border-border text-muted-foreground" },
  elevated: { label: "Elevated", className: "border-[hsl(var(--warning))]/50 text-[hsl(var(--warning))]" },
};

const pct = (v: number) => `${(v * 100).toFixed(0)}%`;
const pct1 = (v: number) => `${(v * 100).toFixed(1)}%`;

function tickDate(value: string): string {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleDateString(undefined, { month: "short", year: "2-digit" });
}

export function RollingVol({ data }: { data: RollingVolatility }) {
  if (data.series.length < 2) return null;
  const state = STATE_STYLE[data.state] ?? STATE_STYLE.normal;
  const hasBench = Boolean(data.benchmark_ticker);

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <CardTitle>Realized volatility, rolling {data.window_days}d</CardTitle>
            <CardDescription>
              Is the book running hotter or cooler than its own normal?
            </CardDescription>
          </div>
          <span
            className={`rounded-full border px-2.5 py-0.5 text-xs font-semibold uppercase tracking-wide ${state.className}`}
          >
            {state.label}
          </span>
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        {data.current != null && data.median != null && (
          <p className="font-mono text-sm tabular-nums text-muted-foreground">
            current {pct1(data.current)} vs {pct1(data.median)} median over the window
          </p>
        )}
        <div style={{ width: "100%", height: 240 }}>
          <ResponsiveContainer>
            <LineChart data={data.series} margin={{ top: 6, right: 8, bottom: 0, left: 0 }}>
              <CartesianGrid stroke={GRID_COLOR} strokeDasharray="3 3" vertical={false} />
              <XAxis
                dataKey="date"
                tickFormatter={tickDate}
                tick={{ fill: AXIS_COLOR, fontSize: 11 }}
                tickLine={false}
                axisLine={{ stroke: GRID_COLOR }}
                minTickGap={40}
              />
              <YAxis
                tickFormatter={pct}
                tick={{ fill: AXIS_COLOR, fontSize: 11 }}
                tickLine={false}
                axisLine={false}
                width={44}
              />
              <Tooltip
                formatter={(value: unknown, name: unknown) => [
                  typeof value === "number" ? pct1(value) : "—",
                  name === "portfolio" ? "Your book" : data.benchmark_ticker ?? "Benchmark",
                ]}
                labelFormatter={(l) => String(l)}
                contentStyle={{
                  background: "hsl(var(--card))",
                  border: `1px solid ${GRID_COLOR}`,
                  borderRadius: 8,
                  fontSize: 12,
                }}
              />
              <Legend
                formatter={(v) => (v === "portfolio" ? "Your book" : data.benchmark_ticker)}
                wrapperStyle={{ fontSize: 12 }}
              />
              <Line
                type="monotone"
                dataKey="portfolio"
                stroke="hsl(var(--primary))"
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
              {hasBench && (
                <Line
                  type="monotone"
                  dataKey="benchmark"
                  stroke={AXIS_COLOR}
                  strokeWidth={1.5}
                  strokeDasharray="4 3"
                  dot={false}
                  connectNulls={false}
                  isAnimationActive={false}
                />
              )}
            </LineChart>
          </ResponsiveContainer>
        </div>
        <p className="text-[11px] text-muted-foreground">
          21-day rolling annualized volatility, leverage-adjusted
          {hasBench ? `; ${data.benchmark_ticker} shown unadjusted` : ""}. The headline
          &quot;Annual vol&quot; KPI uses a faster-reacting EWMA estimator — both are standard.
        </p>
      </CardContent>
    </Card>
  );
}
