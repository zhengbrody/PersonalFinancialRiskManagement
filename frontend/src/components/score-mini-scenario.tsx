"use client";

/**
 * Mini market-crash scenario for the Health Score Overview — a deterministic,
 * first-order read computed ENTIRELY from numbers the score response already
 * returned (beta_to_benchmark, net_equity, var_95_daily). No extra fetch, no
 * AI, no invented figures. For the full per-holding sweep we link to the Risk
 * page's Scenario Explorer (which recomputes per-asset losses on the engine).
 */

import Link from "next/link";
import { useState } from "react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { PortfolioMetrics } from "@/lib/schemas";

const SHOCKS = [-10, -20, -30] as const;

function usd(n: number): string {
  const sign = n < 0 ? "-" : "";
  return `${sign}$${Math.abs(n).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

export function ScoreMiniScenario({ metrics }: { metrics: PortfolioMetrics }) {
  const [shock, setShock] = useState<(typeof SHOCKS)[number]>(-10);

  const base = metrics.net_equity ?? metrics.total_value;
  const beta = metrics.beta_to_benchmark;
  // Need an equity base and a market sensitivity to estimate anything.
  if (base == null || base <= 0 || beta == null || Number.isNaN(beta)) return null;

  const loss = base * beta * (shock / 100);
  const lossPct = (loss / base) * 100;

  // 1-day VaR in dollars (already a daily fraction from the engine).
  const var95 = metrics.var_95_daily;
  const varUsd = var95 == null || Number.isNaN(var95) ? null : -Math.abs(var95) * base;

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">If the market drops</CardTitle>
        <CardDescription>
          First-order estimate from your beta ({beta.toFixed(2)}) — a quick read,
          not the full per-holding sweep.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex gap-2">
          {SHOCKS.map((sh) => (
            <button
              key={sh}
              type="button"
              onClick={() => setShock(sh)}
              aria-pressed={shock === sh}
              className={`rounded-md border px-3 py-1.5 text-sm font-medium tabular-nums transition ${
                shock === sh
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border hover:bg-accent"
              }`}
            >
              {sh}%
            </button>
          ))}
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-lg border border-border bg-muted/20 p-3">
            <p className="text-[10px] uppercase tracking-widest text-muted-foreground">
              Est. portfolio impact
            </p>
            <p className="font-mono text-2xl font-semibold tabular-nums text-red-600 dark:text-red-400">
              {usd(loss)}
            </p>
            <p className="text-xs text-muted-foreground">
              {lossPct.toFixed(1)}% of {usd(base)}
            </p>
          </div>
          <div className="rounded-lg border border-border bg-muted/20 p-3">
            <p className="text-[10px] uppercase tracking-widest text-muted-foreground">
              1-day VaR 95%
            </p>
            <p className="font-mono text-2xl font-semibold tabular-nums">
              {varUsd == null ? "—" : usd(varUsd)}
            </p>
            <p className="text-xs text-muted-foreground">
              Worst ~1-in-20 day, from history
            </p>
          </div>
        </div>

        <p className="text-xs text-muted-foreground">
          Beta-based approximation.{" "}
          <Link href="/scenarios" className="text-primary hover:underline">
            See the full per-holding scenario explorer →
          </Link>
        </p>
      </CardContent>
    </Card>
  );
}
