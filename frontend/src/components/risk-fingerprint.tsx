"use client";

/**
 * Risk fingerprint — a five-axis 0–10 radar of the book's risk intensity,
 * scaled against FIXED reference bands (documented below). Pure client-side
 * arithmetic over numbers the report already carries; higher = more risk.
 * It is an educational shape, NOT a score — the caption says so.
 */

import {
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
} from "recharts";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { RiskReport } from "@/lib/queries";
import { portfolioBeta } from "@/lib/portfolio-beta";

/**
 * Reference bands: the input that pegs an axis at 10/10.
 * β 2.0 = twice the market (β 1.0 → 5); vol 40% annualized (SPY ≈ 16% → 4);
 * HHI 0.05→0.50 span (≥20 effective names → 0, ≤2 → 10); −50% drawdown
 * (2008-scale) pegs; 6% daily CVaR95 pegs (a diversified book ≈ 2% → 3.3).
 */
export const FINGERPRINT_BANDS = {
  beta: 2.0,
  vol: 0.4,
  hhi_floor: 0.05,
  hhi_span: 0.45,
  drawdown: 0.5,
  cvar: 0.06,
} as const;

const clamp10 = (v: number) => Math.max(0, Math.min(10, v));

export function fingerprintAxes(report: RiskReport): { axis: string; value: number }[] {
  const axes: { axis: string; value: number }[] = [];
  const beta = portfolioBeta(report);
  if (beta != null && Number.isFinite(beta)) {
    axes.push({ axis: "Market beta", value: round1(clamp10((Math.abs(beta) / FINGERPRINT_BANDS.beta) * 10)) });
  }
  if (report.annual_volatility != null) {
    axes.push({ axis: "Volatility", value: round1(clamp10((report.annual_volatility / FINGERPRINT_BANDS.vol) * 10)) });
  }
  const hhi = report.concentration?.hhi;
  if (hhi != null) {
    axes.push({
      axis: "Concentration",
      value: round1(clamp10(((hhi - FINGERPRINT_BANDS.hhi_floor) / FINGERPRINT_BANDS.hhi_span) * 10)),
    });
  }
  if (report.max_drawdown != null) {
    axes.push({
      axis: "Drawdown",
      value: round1(clamp10((Math.abs(report.max_drawdown) / FINGERPRINT_BANDS.drawdown) * 10)),
    });
  }
  if (report.cvar_95 != null) {
    axes.push({ axis: "Tail risk", value: round1(clamp10((report.cvar_95 / FINGERPRINT_BANDS.cvar) * 10)) });
  }
  return axes.length >= 3 ? axes : [];
}

const round1 = (v: number) => Math.round(v * 10) / 10;

export function RiskFingerprint({ report }: { report: RiskReport }) {
  const axes = fingerprintAxes(report);
  if (axes.length === 0) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Risk fingerprint</CardTitle>
        <CardDescription>The shape of your risk, at a glance — higher is riskier.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        <div style={{ width: "100%", height: 260 }}>
          <ResponsiveContainer>
            <RadarChart data={axes} cx="50%" cy="50%" outerRadius="72%">
              <PolarGrid stroke="hsl(var(--border))" />
              <PolarAngleAxis
                dataKey="axis"
                tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 11 }}
              />
              <PolarRadiusAxis domain={[0, 10]} tick={false} axisLine={false} />
              <Radar
                dataKey="value"
                stroke="hsl(var(--primary))"
                fill="hsl(var(--primary))"
                fillOpacity={0.25}
                isAnimationActive={false}
              />
            </RadarChart>
          </ResponsiveContainer>
        </div>
        <ul className="grid grid-cols-2 gap-x-4 gap-y-0.5 font-mono text-[11px] tabular-nums text-muted-foreground sm:grid-cols-3">
          {axes.map((a) => (
            <li key={a.axis}>
              {a.axis}: {a.value.toFixed(1)}
            </li>
          ))}
        </ul>
        <p className="text-[11px] text-muted-foreground">
          0–10 risk intensity vs fixed reference bands (β 2.0, vol 40%, HHI 0.5, drawdown −50%,
          daily CVaR 6% each peg at 10) — educational scaling, not a score.
        </p>
      </CardContent>
    </Card>
  );
}
