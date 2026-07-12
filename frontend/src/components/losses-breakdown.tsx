"use client";

/**
 * Losses in BOTH % and $ — 1-day VaR/CVaR, the 21-day VaR (clearly distinguished
 * from the 1-day figures), stress loss, current drawdown, and the margin buffer.
 * All numbers are deterministic (backend `losses`); this only renders. Reuses
 * Kpi + Badge — no new palette.
 */

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Kpi } from "@/components/ui/kpi";
import { Badge, type BadgeTone } from "@/components/ui/badge";
import type { LossBreakdown, LossFigure } from "@/lib/queries";

const usd = (v: number | null | undefined): string =>
  v == null ? "—" : (v < 0 ? "−$" : "$") + Math.abs(Math.round(v)).toLocaleString("en-US");
const pct = (v: number | null | undefined, d = 1): string =>
  v == null ? "—" : `${(v * 100).toFixed(d)}%`;

const MARGIN_TONE: Record<string, BadgeTone> = {
  none: "neutral",
  comfortable: "success",
  tight: "warning",
  call_risk: "danger",
  "n/a": "neutral",
};
const MARGIN_LABEL: Record<string, string> = {
  none: "No margin",
  comfortable: "Comfortable",
  tight: "Tight",
  call_risk: "Call risk",
  "n/a": "n/a",
};

function LossTile({ figure, label }: { figure: LossFigure | null | undefined; label: string }) {
  if (!figure || (figure.pct == null && figure.usd == null)) return null;
  return (
    <Kpi
      label={label}
      value={pct(figure.pct)}
      tone="bad"
      // second line: the dollar magnitude
      delta={usd(figure.usd)}
    />
  );
}

export function LossesBreakdown({
  losses,
}: {
  losses: LossBreakdown | null | undefined;
}) {
  if (!losses) return null;
  const mb = losses.margin_buffer;
  const hasAny =
    losses.var_1d_95 || losses.cvar_1d_95 || losses.var_21d_95 || losses.stress || losses.current_drawdown;
  if (!hasAny && !mb) return null;

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">Potential losses</CardTitle>
        <p className="text-sm text-muted-foreground">
          What a bad day (or a crisis) could cost — shown in both percent and dollars on your net
          equity.
        </p>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-5">
          <LossTile figure={losses.var_1d_95} label="1-day VaR (95%)" />
          <LossTile figure={losses.cvar_1d_95} label="1-day CVaR (95%)" />
          <LossTile figure={losses.var_21d_95} label="21-day VaR (95%)" />
          <LossTile figure={losses.stress} label={losses.stress?.label || "Stress loss"} />
          <LossTile figure={losses.current_drawdown} label="Current drawdown" />
        </div>

        {mb && mb.status !== "n/a" && (
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border bg-muted/30 px-3 py-2 text-sm">
            <div>
              <span className="text-xs uppercase tracking-wide text-muted-foreground">
                Margin buffer
              </span>
              <div className="font-mono tabular-nums">
                {usd(mb.buffer_usd)}
                {mb.buffer_pct != null && (
                  <span className="text-muted-foreground"> · {pct(mb.buffer_pct)} of assets</span>
                )}
              </div>
            </div>
            <Badge tone={MARGIN_TONE[mb.status] ?? "neutral"} uppercase>
              {MARGIN_LABEL[mb.status] ?? mb.status}
            </Badge>
          </div>
        )}
        <p className="text-[11px] text-muted-foreground">
          1-day VaR/CVaR are a 1-day historical estimate; the 21-day VaR is a Monte-Carlo figure —
          they are different horizons, not a discrepancy.
        </p>
      </CardContent>
    </Card>
  );
}
