"use client";

/**
 * Revenue + margin trend (consolidated research page). The earnings timeline,
 * peer scatter, and DCF scenario charts already live inside their own reused
 * components; this adds the one chart that was missing — quarterly revenue ($B)
 * with gross / operating / net margin lines over it. Every value comes from the
 * backend financials; nothing is computed here beyond unit scaling. Renders
 * nothing with fewer than two quarters.
 */

import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { ResearchFactPack } from "@/lib/queries";

export function ResearchCharts({ financials }: { financials?: ResearchFactPack }) {
  const quarters = financials?.quarters ?? [];
  // oldest → newest reads left→right like a time series.
  const data = quarters
    .slice()
    .reverse()
    .filter((q) => q.revenue != null)
    .map((q) => ({
      period: q.period,
      revenue: Math.round((q.revenue as number) / 1e9),
      gross: q.gross_margin != null ? +(q.gross_margin * 100).toFixed(1) : null,
      operating: q.operating_margin != null ? +(q.operating_margin * 100).toFixed(1) : null,
      net: q.net_margin != null ? +(q.net_margin * 100).toFixed(1) : null,
    }));

  if (data.length < 2) return null;

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Revenue &amp; margin trend</CardTitle>
        <CardDescription>
          Quarterly revenue ($B, bars) with gross / operating / net margin (%, lines) · oldest →
          newest
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="h-64 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -8 }}>
              <CartesianGrid stroke="hsl(var(--border))" strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="period" tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }} />
              <YAxis
                yAxisId="rev"
                tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
                width={36}
              />
              <YAxis
                yAxisId="mgn"
                orientation="right"
                unit="%"
                tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
                width={40}
              />
              <Tooltip
                contentStyle={{
                  background: "hsl(var(--card))",
                  border: "1px solid hsl(var(--border))",
                  borderRadius: 8,
                  fontSize: 12,
                }}
                formatter={(value, name) =>
                  name === "Revenue" ? [`$${Number(value)}B`, name] : [`${Number(value)}%`, name]
                }
              />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Bar
                yAxisId="rev"
                dataKey="revenue"
                name="Revenue"
                fill="hsl(var(--primary))"
                radius={[3, 3, 0, 0]}
                opacity={0.85}
              />
              <Line yAxisId="mgn" dataKey="gross" name="Gross %" stroke="#10b981" strokeWidth={2} dot={false} />
              <Line yAxisId="mgn" dataKey="operating" name="Op %" stroke="#3b82f6" strokeWidth={2} dot={false} />
              <Line yAxisId="mgn" dataKey="net" name="Net %" stroke="#D4A017" strokeWidth={2} dot={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  );
}
