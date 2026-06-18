"use client";

/**
 * Mini sparkline (MindMarket design system — components/charts/Sparkline). A
 * tiny, axis-less inline trend for KPI tiles / heroes. Auto-tones up = success,
 * down = destructive (flip with `invert` for "down is good" metrics like
 * volatility). Renders nothing with < 2 points so it hides until history exists.
 */

import { Line, LineChart, ResponsiveContainer } from "recharts";

export function MiniSparkline({
  data,
  width = 72,
  height = 24,
  invert = false,
}: {
  data: number[] | undefined;
  width?: number;
  height?: number;
  invert?: boolean;
}) {
  const points = (data ?? []).filter((v) => Number.isFinite(v));
  if (points.length < 2) return null;

  const rising = points[points.length - 1] >= points[0];
  const good = invert ? !rising : rising;
  const color = good ? "hsl(var(--success))" : "hsl(var(--destructive))";
  const series = points.map((v, i) => ({ i, v }));

  return (
    <div style={{ width, height }} aria-hidden>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={series} margin={{ top: 3, right: 1, bottom: 3, left: 1 }}>
          <Line
            type="monotone"
            dataKey="v"
            stroke={color}
            strokeWidth={1.5}
            dot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
