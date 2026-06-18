"use client";

/**
 * Allocation donut (MindMarket design system — components/charts/DonutChart).
 * Visualises where the book is concentrated by sector (or any {label, weight}
 * slices). Top-N slices + an "Other" roll-up, a center label, and a compact
 * legend. Theme-aware via CSS-var/brand colours. Pure display — give it the
 * sector weights the score response already carries (concentration.sectors).
 */

import { Cell, Pie, PieChart, ResponsiveContainer } from "recharts";

export type DonutSlice = { label: string; weight: number };

// Distinct, theme-coherent slice colours (primary + brand teal/gold + a few
// accents, "Other" muted). Fixed hexes for the brand accents so they read the
// same in light & dark; primary/muted track the theme.
const PALETTE = [
  "hsl(var(--primary))",
  "#39A3B5",
  "#D4A017",
  "#15803d",
  "#a855f7",
  "#ef4444",
];
const OTHER_COLOR = "hsl(var(--muted-foreground))";

export function AllocationDonut({
  slices,
  centerTop,
  centerSub,
  topN = 5,
  size = 132,
}: {
  slices: DonutSlice[] | undefined;
  centerTop?: string;
  centerSub?: string;
  topN?: number;
  size?: number;
}) {
  const clean = (slices ?? []).filter((s) => Number.isFinite(s.weight) && s.weight > 0);
  if (clean.length === 0) return null;

  const sorted = [...clean].sort((a, b) => b.weight - a.weight);
  const top = sorted.slice(0, topN);
  const otherWeight = sorted.slice(topN).reduce((a, s) => a + s.weight, 0);
  const data = otherWeight > 0.001 ? [...top, { label: "Other", weight: otherWeight }] : top;
  const colorOf = (i: number, label: string) =>
    label === "Other" ? OTHER_COLOR : PALETTE[i % PALETTE.length];
  const pct = (w: number) => `${(w * 100).toFixed(0)}%`;

  return (
    <div className="flex items-center gap-4">
      <div className="relative shrink-0" style={{ width: size, height: size }}>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={data}
              dataKey="weight"
              nameKey="label"
              innerRadius="62%"
              outerRadius="100%"
              paddingAngle={1.5}
              stroke="hsl(var(--card))"
              strokeWidth={2}
              isAnimationActive={false}
            >
              {data.map((s, i) => (
                <Cell key={s.label} fill={colorOf(i, s.label)} />
              ))}
            </Pie>
          </PieChart>
        </ResponsiveContainer>
        {(centerTop || centerSub) && (
          <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center text-center">
            {centerTop && <span className="font-mono text-lg font-semibold tabular-nums">{centerTop}</span>}
            {centerSub && <span className="text-[10px] text-muted-foreground">{centerSub}</span>}
          </div>
        )}
      </div>
      <ul className="min-w-0 flex-1 space-y-1 text-xs">
        {data.map((s, i) => (
          <li key={s.label} className="flex items-center gap-2">
            <span
              aria-hidden
              className="h-2.5 w-2.5 shrink-0 rounded-sm"
              style={{ background: colorOf(i, s.label) }}
            />
            <span className="min-w-0 flex-1 truncate text-muted-foreground">{s.label}</span>
            <span className="font-mono tabular-nums">{pct(s.weight)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
