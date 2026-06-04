"use client";

/**
 * Theme-aware horizontal bar chart (recharts) — the bar counterpart to
 * TimeSeriesChart. Used for factor betas, component-VaR contribution, and
 * stress-loss ranked bars. Colors are CSS-variable driven so it tracks the
 * market-synced light/dark theme; per-bar color override supported (e.g. red
 * for losses, emerald for gains).
 */

import {
  Bar,
  BarChart,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export type BarDatum = { label: string; value: number; color?: string };

const AXIS_COLOR = "hsl(var(--muted-foreground))";
const DEFAULT_COLOR = "hsl(var(--primary))";

type TooltipRenderProps = {
  active?: boolean;
  payload?: ReadonlyArray<{ value?: unknown; payload?: BarDatum }>;
};

export function HorizontalBarChart({
  data,
  height,
  valueFormatter = (v) => v.toLocaleString(),
  ariaLabel,
}: {
  data: BarDatum[];
  height?: number;
  valueFormatter?: (value: number) => string;
  ariaLabel?: string;
}) {
  // Height scales with row count so labels never overlap.
  const h = height ?? Math.max(120, data.length * 34 + 16);

  function Tip(props: TooltipRenderProps) {
    if (!props.active || !props.payload || props.payload.length === 0) return null;
    const raw = props.payload[0]?.value;
    const label = props.payload[0]?.payload?.label;
    if (typeof raw !== "number") return null;
    return (
      <div className="rounded-md border border-border bg-card px-3 py-2 text-xs shadow-sm">
        <p className="text-muted-foreground">{label}</p>
        <p className="font-mono font-medium text-foreground">{valueFormatter(raw)}</p>
      </div>
    );
  }

  return (
    <div style={{ width: "100%", height: h }} role="img" aria-label={ariaLabel} data-testid="bar-chart">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 12, left: 4, bottom: 4 }}>
          <XAxis
            type="number"
            tickFormatter={valueFormatter}
            stroke={AXIS_COLOR}
            tick={{ fontSize: 11, fill: AXIS_COLOR }}
            tickLine={false}
            axisLine={false}
          />
          <YAxis
            type="category"
            dataKey="label"
            width={64}
            stroke={AXIS_COLOR}
            tick={{ fontSize: 11, fill: AXIS_COLOR }}
            tickLine={false}
            axisLine={false}
          />
          <Tooltip content={Tip} cursor={{ fill: "hsl(var(--muted) / 0.4)" }} />
          <Bar dataKey="value" radius={[0, 3, 3, 0]} isAnimationActive={false}>
            {data.map((d, i) => (
              <Cell key={i} fill={d.color ?? DEFAULT_COLOR} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
