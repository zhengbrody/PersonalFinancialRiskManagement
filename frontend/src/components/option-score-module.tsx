"use client";

/**
 * "Options are affecting this score" — a concise, deterministic module on the
 * Health Score page. Shows the capped penalty the option book applied (base −
 * penalty) and the top-2 drivers, sourced verbatim from the score response's
 * `options` block (computed in Python — no LLM). Hidden when the book has no
 * options or took no penalty.
 */

import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { OptionScoreImpact } from "@/lib/schemas";

const FLAG_LABEL: Record<string, string> = {
  uncovered_short_call: "Uncovered short call",
  under_collateralized_short: "Under-collateralized short",
  short_gamma: "Net short gamma",
  large_negative_theta: "Heavy time decay (theta)",
  concentrated_expiry: "Concentrated in one expiry",
  high_single_underlying: "Concentrated in one underlying",
  missing_option_data: "Missing option price/IV",
};

export function OptionScoreModule({ impact }: { impact: OptionScoreImpact | null | undefined }) {
  if (!impact || impact.penalty <= 0) return null;

  const top = [...impact.penalty_breakdown].sort((a, b) => b.points - a.points).slice(0, 2);

  return (
    <Card className="border-amber-500/30">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center justify-between text-sm">
          <span>Options are affecting this score</span>
          <span className="font-mono text-amber-600 dark:text-amber-400">
            −{impact.penalty} pts
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <p className="text-muted-foreground">
          Your {impact.contracts} option contract{impact.contracts === 1 ? "" : "s"} carry risks the
          equity score can&apos;t see. Base{" "}
          <span className="font-mono text-foreground">{impact.base_score}</span> → adjusted{" "}
          <span className="font-mono text-foreground">{impact.base_score - impact.penalty}</span>.
        </p>
        <div className="grid grid-cols-4 gap-2 text-center">
          <Greek label="Net Δ" value={impact.net_delta} />
          <Greek label="Γ" value={impact.net_gamma} />
          <Greek label="Θ / day" value={impact.net_theta} />
          <Greek label="ν" value={impact.net_vega} />
        </div>
        <ul className="space-y-1">
          {top.map((d, i) => (
            <li key={i} className="flex items-center gap-2 text-xs">
              <span className="inline-block h-1.5 w-1.5 rounded-full bg-amber-500" />
              <span>{FLAG_LABEL[d.code] ?? d.code}</span>
              <span className="ml-auto font-mono text-muted-foreground">−{d.points}</span>
            </li>
          ))}
        </ul>
        <p className="text-xs">
          <Link href="/risk" className="text-primary hover:underline">
            Inspect option risk →
          </Link>{" "}
          <span className="text-muted-foreground">· Educational, not financial advice.</span>
        </p>
      </CardContent>
    </Card>
  );
}

/** A single net-Greek tile (signed, tabular). */
function Greek({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md border border-border bg-background/40 p-1.5">
      <p className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="font-mono text-sm tabular-nums">
        {value >= 0 ? "+" : ""}
        {value.toFixed(2)}
      </p>
    </div>
  );
}
