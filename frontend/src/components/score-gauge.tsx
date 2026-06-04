"use client";

/**
 * Horizontal 0–1000 Portfolio Health gauge with four bands and a marker at the
 * current score. Bands match the backend severity thresholds
 * (services/risk_explain.py): Poor <400 · Watch <650 · Healthy <850 · Strong.
 * Pure CSS/Tailwind, theme-token friendly.
 */

import { cn } from "@/lib/utils";

export type ScoreBand = "Poor" | "Watch" | "Healthy" | "Strong";

const BANDS: { label: ScoreBand; from: number; to: number; bar: string; text: string }[] = [
  { label: "Poor", from: 0, to: 400, bar: "bg-red-500/70", text: "text-red-600 dark:text-red-400" },
  { label: "Watch", from: 400, to: 650, bar: "bg-amber-500/70", text: "text-amber-600 dark:text-amber-400" },
  { label: "Healthy", from: 650, to: 850, bar: "bg-emerald-400/70", text: "text-emerald-600 dark:text-emerald-400" },
  { label: "Strong", from: 850, to: 1000, bar: "bg-emerald-600/80", text: "text-emerald-700 dark:text-emerald-300" },
];

export function scoreBand(score: number): { label: ScoreBand; text: string } {
  const b = BANDS.find((x) => score < x.to) ?? BANDS[BANDS.length - 1];
  return { label: b.label, text: b.text };
}

export function ScoreGauge({ score, className }: { score: number; className?: string }) {
  const clamped = Math.max(0, Math.min(1000, score));
  const pct = (clamped / 1000) * 100;
  const band = scoreBand(clamped);

  return (
    <div className={cn("space-y-1.5", className)}>
      <div className="flex items-baseline justify-between">
        <span className="text-xs uppercase tracking-widest text-muted-foreground">
          Health band
        </span>
        <span className={cn("text-xs font-semibold uppercase tracking-wide", band.text)}>
          {band.label}
        </span>
      </div>

      <div className="relative h-3 w-full overflow-hidden rounded-full">
        {/* band segments */}
        <div className="absolute inset-0 flex">
          {BANDS.map((b) => (
            <div
              key={b.label}
              className={b.bar}
              style={{ width: `${((b.to - b.from) / 1000) * 100}%` }}
            />
          ))}
        </div>
        {/* marker */}
        <div
          className="absolute top-1/2 h-5 w-1 -translate-x-1/2 -translate-y-1/2 rounded-full bg-foreground shadow ring-2 ring-background"
          style={{ left: `${pct}%` }}
          aria-hidden
        />
      </div>

      <div className="flex justify-between text-[10px] text-muted-foreground">
        <span>0</span>
        <span>400</span>
        <span>650</span>
        <span>850</span>
        <span>1000</span>
      </div>
    </div>
  );
}
