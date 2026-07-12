"use client";

/**
 * Explainable risk-dimension grid — one card per dimension (concentration,
 * volatility, drawdown, beta, correlation, liquidity, leverage, options), each
 * with value · status · historical percentile · attention share · confidence ·
 * plain-English explanation · an Ask-Copilot action. Every number is
 * deterministic (from the backend `dimensions[]`); this component only renders.
 * Reuses Card + Badge + the design tokens — no new palette.
 */

import Link from "next/link";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge, type BadgeTone } from "@/components/ui/badge";
import type { RiskDimension } from "@/lib/queries";
import { cn } from "@/lib/utils";

const STATUS_TONE: Record<string, BadgeTone> = {
  calm: "success",
  normal: "neutral",
  elevated: "warning",
  high: "danger",
  "n/a": "neutral",
};
const STATUS_LABEL: Record<string, string> = {
  calm: "Calm",
  normal: "Normal",
  elevated: "Elevated",
  high: "High",
  "n/a": "Not measurable",
};

function ConfidenceChip({ confidence }: { confidence?: string | null }) {
  if (!confidence) return null;
  return (
    <span
      className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground"
      title="How much to trust this dimension given the data behind it"
    >
      {confidence} confidence
    </span>
  );
}

function DimensionCard({ dim }: { dim: RiskDimension }) {
  const measurable = dim.measurable !== false && dim.status !== "n/a";
  const tone = STATUS_TONE[dim.status] ?? "neutral";
  const pct =
    dim.percentile != null ? Math.round(dim.percentile * 100) : null;
  const share =
    dim.contribution != null ? Math.round(dim.contribution * 100) : null;

  return (
    <Card className={cn(!measurable && "opacity-70")}>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="text-sm">{dim.name}</CardTitle>
          <Badge tone={tone} uppercase>
            {STATUS_LABEL[dim.status] ?? dim.status}
          </Badge>
        </div>
        {measurable && dim.display && (
          <div className="pt-1 font-mono text-2xl tabular-nums text-foreground">
            {dim.display}
          </div>
        )}
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        <p className="text-muted-foreground">{dim.explanation}</p>

        {measurable && (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            {pct != null && (
              <span title={`Vs ${dim.percentile_n ?? 0} of your past readings`}>
                Higher than <span className="font-medium text-foreground">{pct}%</span> of your
                history
              </span>
            )}
            <ConfidenceChip confidence={dim.confidence} />
          </div>
        )}

        {measurable && share != null && (
          <div>
            <div className="mb-0.5 flex items-center justify-between text-[10px] uppercase tracking-wide text-muted-foreground">
              <span>Share of current risk attention</span>
              <span className="tabular-nums">{share}%</span>
            </div>
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-primary/70"
                style={{ width: `${Math.min(100, share)}%` }}
              />
            </div>
          </div>
        )}

        {dim.action && (
          <Link
            href={`/copilot?q=${encodeURIComponent(dim.action)}`}
            className="inline-block text-xs font-medium text-primary hover:underline"
          >
            Ask Copilot →
          </Link>
        )}
      </CardContent>
    </Card>
  );
}

export function RiskDimensionsGrid({
  dimensions,
}: {
  dimensions: RiskDimension[] | undefined | null;
}) {
  if (!dimensions || dimensions.length === 0) return null;
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">Risk dimensions</CardTitle>
        <p className="text-sm text-muted-foreground">
          Every angle of your risk, ranked by where to look first. Percentiles compare each
          number to your own history.
        </p>
      </CardHeader>
      <CardContent>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {dimensions.map((d) => (
            <DimensionCard key={d.key} dim={d} />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
