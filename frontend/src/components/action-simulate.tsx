"use client";

/**
 * Upgraded Action Cards — deterministic risk LEVERS with expected impact.
 * Each card shows a proposed change, the EXPECTED score/VaR/CVaR delta
 * (re-scored by the backend on the user's real returns), trade-offs,
 * assumptions, and a "Simulate" toggle that reveals the proposed book. It NEVER
 * executes a trade. Reuses Card + Kpi + Badge — no new palette.
 */

import { useState } from "react";
import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useSimulateActions, type ActionCard as ActionCardT } from "@/lib/queries";
import { track } from "@/lib/analytics";
import { Skeleton } from "@/components/ui/skeleton";

const usd = (v: number | null | undefined): string =>
  v == null ? "—" : (v < 0 ? "−$" : "$") + Math.abs(Math.round(v)).toLocaleString("en-US");
const signedPts = (v: number | null | undefined): string =>
  v == null ? "—" : `${v > 0 ? "+" : ""}${v}`;
const signedPct = (v: number | null | undefined, d = 2): string =>
  v == null ? "—" : `${v > 0 ? "+" : ""}${(v * 100).toFixed(d)}%`;

/** A signed impact chip. `goodWhenNegative` flips the tone (lower VaR is good). */
function ImpactChip({
  label,
  value,
  goodWhenNegative = false,
}: {
  label: string;
  value: string;
  goodWhenNegative?: boolean;
}) {
  const neg = value.startsWith("−") || value.startsWith("-");
  const pos = value.startsWith("+");
  const good = goodWhenNegative ? neg : pos;
  const bad = goodWhenNegative ? pos : neg;
  const tone = good ? "success" : bad ? "danger" : "neutral";
  return (
    <div className="flex flex-col">
      <span className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</span>
      <Badge tone={tone} className="mt-0.5 font-mono tabular-nums">
        {value}
      </Badge>
    </div>
  );
}

function LeverCard({ card }: { card: ActionCardT }) {
  const [open, setOpen] = useState(false);
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">{card.title}</CardTitle>
        <p className="pt-1 text-sm text-muted-foreground">{card.rationale}</p>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <p className="font-medium">{card.proposed_change}</p>

        <div className="flex flex-wrap gap-4">
          <ImpactChip
            label="Health score"
            value={
              card.expected_score_delta != null && card.expected_score_after != null
                ? `${signedPts(card.expected_score_delta)} → ${card.expected_score_after}`
                : signedPts(card.expected_score_delta)
            }
          />
          <ImpactChip label="1-day VaR" value={signedPct(card.expected_var_delta)} goodWhenNegative />
          <ImpactChip
            label="1-day CVaR"
            value={signedPct(card.expected_cvar_delta)}
            goodWhenNegative
          />
        </div>

        {card.trade_offs.length > 0 && (
          <div>
            <span className="text-xs uppercase tracking-wide text-muted-foreground">Trade-offs</span>
            <ul className="mt-0.5 space-y-0.5">
              {card.trade_offs.map((t, i) => (
                <li key={i} className="flex gap-2">
                  <span aria-hidden className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-warning/70" />
                  <span>{t}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        <button
          type="button"
          onClick={() => {
            setOpen((v) => !v);
            if (!open) track("action_simulated", { lever: card.key });
          }}
          className="text-xs font-medium text-primary hover:underline"
          aria-expanded={open}
        >
          {open ? "Hide simulation" : "Simulate this change →"}
        </button>

        {open && (
          <div className="space-y-2 rounded-md border border-border bg-muted/30 px-3 py-2">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Simulated portfolio (nothing is traded)
            </p>
            <div className="max-h-48 overflow-y-auto">
              <table className="w-full text-xs tabular-nums">
                <tbody>
                  {card.simulate_holdings.map((h) => (
                    <tr key={h.ticker} className="border-b border-border/50 last:border-0">
                      <td className="py-1 font-mono">{h.ticker}</td>
                      <td className="py-1 text-right text-muted-foreground">{usd(h.market_value)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {card.assumptions.length > 0 && (
              <ul className="space-y-0.5 border-t border-border pt-1.5 text-[11px] text-muted-foreground">
                {card.assumptions.map((a, i) => (
                  <li key={i}>• {a}</li>
                ))}
              </ul>
            )}
            <Link
              href="#whatif"
              className="inline-block text-xs font-medium text-primary hover:underline"
            >
              Open the what-if lab to adjust →
            </Link>
          </div>
        )}

        {card.disclaimer && (
          <p className="text-[11px] italic text-muted-foreground">{card.disclaimer}</p>
        )}
      </CardContent>
    </Card>
  );
}

export function ActionSimulate({ fallback }: { fallback?: React.ReactNode }) {
  const q = useSimulateActions();

  if (q.isLoading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }
  // On error or no levers, fall back to the educational action cards.
  const actions = q.data?.actions ?? [];
  if (q.isError || actions.length === 0) {
    return <>{fallback ?? null}</>;
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        Deterministic risk levers with their expected impact, re-scored on your real portfolio.
        Simulations only — nothing is traded.
      </p>
      {actions.map((c) => (
        <LeverCard key={c.key} card={c} />
      ))}
    </div>
  );
}
