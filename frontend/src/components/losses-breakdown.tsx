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
import type { FinancingResilience } from "@/lib/schemas";

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
const FINANCING_TONE: Record<string, BadgeTone> = {
  no_margin: "neutral",
  covered: "success",
  partial: "warning",
  uncovered: "danger",
  impaired: "danger",
};
const FINANCING_LABEL: Record<string, string> = {
  no_margin: "No margin",
  covered: "Covered",
  partial: "Partly covered",
  uncovered: "Not covered",
  impaired: "Equity impaired",
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
  financing,
}: {
  losses: LossBreakdown | null | undefined;
  financing?: FinancingResilience | null;
}) {
  const mb = losses?.margin_buffer;
  const hasAny =
    losses?.var_1d_95 || losses?.cvar_1d_95 || losses?.var_21d_95 || losses?.stress || losses?.current_drawdown;
  // The financing block only renders when there IS a loan, so a financing
  // object alone doesn't justify the card — without this, a no-margin book
  // whose losses failed to compute would render five empty "—" tiles.
  const showsFinancing = Boolean(financing && financing.margin_loan > 0);
  if (!hasAny && !mb && !showsFinancing) return null;

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
          <LossTile figure={losses?.var_1d_95} label="1-day VaR (95%)" />
          <LossTile figure={losses?.cvar_1d_95} label="1-day CVaR (95%)" />
          <LossTile figure={losses?.var_21d_95} label="21-day VaR (95%)" />
          <LossTile figure={losses?.stress} label={losses?.stress?.label || "Stress loss"} />
          <LossTile figure={losses?.current_drawdown} label="Current drawdown" />
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
        {financing && financing.margin_loan > 0 && (
          <div className="rounded-md border border-border bg-muted/20 px-3 py-3 text-sm">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <span className="text-xs uppercase tracking-wide text-muted-foreground">
                  Financing resilience
                </span>
                <div className="mt-1 font-mono tabular-nums">
                  {financing.margin_coverage_ratio == null
                    ? "—"
                    : /* the ratio can exceed 1 — clamp the DISPLAY so an
                         over-collateralised book doesn't read "250% covered" */
                      `${Math.min(financing.margin_coverage_ratio * 100, 100).toFixed(0)}%`}{" "}
                  <span className="font-sans text-muted-foreground">of margin covered</span>
                </div>
              </div>
              <Badge tone={FINANCING_TONE[financing.status] ?? "neutral"} uppercase>
                {FINANCING_LABEL[financing.status] ?? financing.status}
              </Badge>
            </div>
            <div className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1 text-xs sm:grid-cols-4">
              <div>
                <span className="text-muted-foreground">Cash equivalents</span>
                <div className="font-mono">{usd(financing.cash_equivalent_value)}</div>
              </div>
              <div>
                <span className="text-muted-foreground">Residual margin</span>
                <div className="font-mono">{usd(financing.residual_margin)}</div>
              </div>
              <div>
                <span className="text-muted-foreground">Gross leverage</span>
                <div className="font-mono">
                  {financing.gross_leverage == null ? "—" : `${financing.gross_leverage.toFixed(2)}×`}
                </div>
              </div>
              <div>
                <span className="text-muted-foreground">Post-offset risk leverage</span>
                <div className="font-mono">
                  {financing.post_offset_risk_leverage == null
                    ? "—"
                    : `${financing.post_offset_risk_leverage.toFixed(2)}×`}
                </div>
              </div>
            </div>
            <p className="mt-2 text-[11px] text-muted-foreground">
              {financing.methodology_note}
              {financing.cash_equivalents.some((h) => h.classification_source === "explicit") && (
                <>
                  {" "}
                  Includes{" "}
                  {financing.cash_equivalents
                    .filter((h) => h.classification_source === "explicit")
                    .map((h) => h.ticker)
                    .join(", ")}
                  , which you classified as cash-like — taken at your word, not verified.
                </>
              )}
            </p>
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
