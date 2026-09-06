"use client";

/**
 * Terminal-style market status strip under the site header — the
 * institutional signature (Bloomberg / trading-floor feel): session state,
 * VIX, Fear & Greed, and the yield curve in one dense mono line.
 *
 * All values come from the public, server-cached /macro/regime endpoint
 * (the same data the /markets page renders) — nothing is computed here.
 * Fail-soft: renders nothing until data exists, so a dead provider never
 * leaves a broken strip.
 */

import { useEffect, useState } from "react";
import { isUsTradingHours } from "@/lib/market-hours";
import { useMarketRegime } from "@/lib/queries";

export function MarketStatusBar() {
  const regime = useMarketRegime();

  // Session state is client-time-derived → compute after mount to keep the
  // SSR HTML stable, and refresh each minute so the open/close flip shows.
  const [open, setOpen] = useState<boolean | null>(null);
  useEffect(() => {
    const tick = () => setOpen(isUsTradingHours());
    tick();
    const id = setInterval(tick, 60_000);
    return () => clearInterval(id);
  }, []);

  const d = regime.data;
  if (!d || open === null) return null;

  const vix = d.vix?.current;
  const vixChange = d.vix?.change;
  const fg = d.fear_greed?.score;
  const fgRating = d.fear_greed?.rating;
  const curve = d.yield_curve?.status;
  const spread = d.yield_curve?.spread_3m_10y;

  return (
    <div className="border-b border-border bg-muted/40">
      <div className="mx-auto flex max-w-[1400px] items-center gap-x-5 overflow-x-auto whitespace-nowrap px-4 py-1.5 text-[11px] text-muted-foreground lg:px-8">
        <span className="flex items-center gap-1.5">
          <span
            aria-hidden
            className={`inline-block h-1.5 w-1.5 rounded-full ${
              open ? "bg-[hsl(var(--success))]" : "bg-muted-foreground/50"
            }`}
          />
          <span className="uppercase tracking-wider">
            US market {open ? "open" : "closed"}
          </span>
        </span>
        {vix != null && (
          <Quote
            label="VIX"
            value={vix.toFixed(1)}
            delta={vixChange}
            deltaInvert
            deltaPercent
          />
        )}
        {fg != null && (
          <span>
            <Label>F&amp;G</Label> {Math.round(fg)}
            {fgRating ? ` ${fgRating}` : ""}
          </span>
        )}
        {curve && (
          <span>
            <Label>Curve</Label> {curve}
            {spread != null ? ` (${spread >= 0 ? "+" : ""}${spread.toFixed(2)})` : ""}
          </span>
        )}
      </div>
    </div>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return (
    <span className="uppercase tracking-wider text-muted-foreground/70">
      {children}
    </span>
  );
}

function Quote({
  label,
  value,
  delta,
  deltaInvert,
  deltaPercent,
}: {
  label: string;
  value: string;
  delta?: number | null;
  /** true when a RISING value is bad (e.g. VIX). */
  deltaInvert?: boolean;
  /** true when the API value is a fractional return (0.01 = +1%). */
  deltaPercent?: boolean;
}) {
  const good = delta != null && (deltaInvert ? delta < 0 : delta > 0);
  const shownDelta = delta != null ? delta * (deltaPercent ? 100 : 1) : null;
  return (
    <span>
      <Label>{label}</Label> {value}
      {shownDelta != null && (
        <span
          className={
            good ? "text-[hsl(var(--success))]" : "text-destructive"
          }
        >
          {" "}
          {shownDelta >= 0 ? "+" : ""}
          {shownDelta.toFixed(1)}
          {deltaPercent ? "%" : ""}
        </span>
      )}
    </span>
  );
}
