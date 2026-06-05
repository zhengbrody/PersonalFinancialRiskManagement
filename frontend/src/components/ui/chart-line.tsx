"use client";

/**
 * A small, theme-aware recharts wrapper used across the Quant Lab.
 *
 * Two chart shapes share one component so future Quant tabs reuse the
 * same axes / tooltip / theming: a `line` (the equity curve — "how
 * your money would have grown") and an `area` (the drawdown — "how far
 * it dropped along the way").
 *
 * Theming: every color is driven by the app's semantic CSS variables
 * (`hsl(var(--primary))`, `hsl(var(--border))`, …) or a caller-supplied
 * token color, so the chart adapts automatically to the market-synced
 * light/dark theme — no hardcoded hex anywhere.
 */

import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export type ChartPoint = { date: string; value: number };

export type TimeSeriesChartProps = {
  data: ChartPoint[];
  /** "line" = equity curve, "area" = drawdown. */
  variant?: "line" | "area";
  /**
   * Stroke/fill color as a CSS color string. Defaults to the theme's
   * primary. Pass `"hsl(var(--destructive))"` or a Tailwind-resolved
   * color for the drawdown tone.
   */
  color?: string;
  height?: number;
  /** Formats the Y axis + tooltip value (e.g. percent or currency). */
  valueFormatter?: (value: number) => string;
  /**
   * Formats the X-axis + tooltip date. Default is "Mon 'YY" — right for a
   * multi-year series (the backtest). For a short, day-by-day series (e.g. the
   * snapshot trends) pass a day-granular formatter so points don't collapse to
   * the same month label.
   */
  dateFormatter?: (value: string) => string;
  /** Accessible label for the chart region. */
  ariaLabel?: string;
};

const AXIS_COLOR = "hsl(var(--muted-foreground))";
const GRID_COLOR = "hsl(var(--border))";

function formatDateTick(value: string): string {
  // ISO date → "Mon 'YY" for a calm, readable axis (years-long series).
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleDateString(undefined, { month: "short", year: "2-digit" });
}

type TooltipRenderProps = {
  active?: boolean;
  payload?: ReadonlyArray<{ value?: unknown }>;
  label?: string | number;
};

function ChartTooltip({
  valueFormatter,
  dateFormatter,
}: {
  valueFormatter: (value: number) => string;
  dateFormatter: (value: string) => string;
}) {
  // recharts injects active/payload/label as props at render time.
  return function Render(props: TooltipRenderProps) {
    const { active, payload, label } = props;
    if (!active || !payload || payload.length === 0) return null;
    const raw = payload[0]?.value;
    if (typeof raw !== "number") return null;
    return (
      <div className="rounded-md border border-border bg-card px-3 py-2 text-xs shadow-sm">
        <p className="text-muted-foreground">{dateFormatter(String(label))}</p>
        <p className="font-mono font-medium text-foreground">
          {valueFormatter(raw)}
        </p>
      </div>
    );
  };
}

export function TimeSeriesChart({
  data,
  variant = "line",
  color = "hsl(var(--primary))",
  height = 280,
  valueFormatter = (v) => v.toLocaleString(),
  dateFormatter = formatDateTick,
  ariaLabel,
}: TimeSeriesChartProps) {
  const gradientId = `chart-fill-${variant}`;
  const Tip = ChartTooltip({ valueFormatter, dateFormatter });

  return (
    <div
      style={{ width: "100%", height }}
      role="img"
      aria-label={ariaLabel}
      data-testid="time-series-chart"
    >
      <ResponsiveContainer width="100%" height="100%">
        {variant === "area" ? (
          <AreaChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={color} stopOpacity={0.35} />
                <stop offset="100%" stopColor={color} stopOpacity={0.02} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke={GRID_COLOR} strokeDasharray="3 3" vertical={false} />
            <XAxis
              dataKey="date"
              tickFormatter={dateFormatter}
              stroke={AXIS_COLOR}
              tick={{ fontSize: 11, fill: AXIS_COLOR }}
              minTickGap={32}
              tickLine={false}
              axisLine={{ stroke: GRID_COLOR }}
            />
            <YAxis
              tickFormatter={valueFormatter}
              stroke={AXIS_COLOR}
              tick={{ fontSize: 11, fill: AXIS_COLOR }}
              width={56}
              tickLine={false}
              axisLine={false}
            />
            <Tooltip content={Tip} />
            <Area
              type="monotone"
              dataKey="value"
              stroke={color}
              strokeWidth={2}
              fill={`url(#${gradientId})`}
              isAnimationActive={false}
            />
          </AreaChart>
        ) : (
          <LineChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid stroke={GRID_COLOR} strokeDasharray="3 3" vertical={false} />
            <XAxis
              dataKey="date"
              tickFormatter={dateFormatter}
              stroke={AXIS_COLOR}
              tick={{ fontSize: 11, fill: AXIS_COLOR }}
              minTickGap={32}
              tickLine={false}
              axisLine={{ stroke: GRID_COLOR }}
            />
            <YAxis
              tickFormatter={valueFormatter}
              stroke={AXIS_COLOR}
              tick={{ fontSize: 11, fill: AXIS_COLOR }}
              width={56}
              tickLine={false}
              axisLine={false}
            />
            <Tooltip content={Tip} />
            <Line
              type="monotone"
              dataKey="value"
              stroke={color}
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
          </LineChart>
        )}
      </ResponsiveContainer>
    </div>
  );
}
