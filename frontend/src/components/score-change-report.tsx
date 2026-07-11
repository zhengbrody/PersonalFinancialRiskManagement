"use client";

/**
 * Deterministic "Why did my score change?" — driven entirely by the backend
 * /risk/score_changes engine (Slice 3), which diffs the live score against the
 * user's OWN prior snapshot (previous-day / 7d / 30d). Every number here is
 * computed server-side; nothing is LLM-narrated. This is the user-facing answer
 * to "my Health Score dropped — why?".
 */

import { useMemo, useState } from "react";
import Link from "next/link";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { track } from "@/lib/analytics";
import { useScoreChanges } from "@/lib/queries";
import type { ScoreChangeReport } from "@/lib/queries";
import type { ScoreResponse } from "@/lib/schemas";

const WINDOWS: { key: string; label: string }[] = [
  { key: "previous", label: "Since last" },
  { key: "7d", label: "7 days" },
  { key: "30d", label: "30 days" },
];

function buildRequest(score: ScoreResponse, window: string): Record<string, unknown> {
  const dimensions: Record<string, number> = {};
  for (const [k, d] of Object.entries(score.dimensions ?? {})) {
    if (d && typeof d.score === "number") dimensions[k] = d.score;
  }
  const m = score.metrics;
  return {
    window,
    overall_score: score.overall_score,
    base_overall: score.base_overall ?? score.overall_score,
    dimensions,
    metrics: {
      annual_volatility: m.annual_volatility ?? null,
      sharpe_ratio: m.sharpe_ratio ?? null,
      max_drawdown: m.max_drawdown ?? null,
      var_95_daily: m.var_95_daily ?? null,
      beta_to_benchmark: m.beta_to_benchmark ?? null,
      net_equity: m.net_equity ?? null,
      leverage: m.leverage ?? null,
    },
    confidence: m.confidence ?? null,
    data_quality: m.data_quality ?? null,
    observations: m.observations ?? null,
    data_coverage: m.data_coverage ?? null,
    dropped_tickers: m.dropped_tickers ?? [],
  };
}

function fmt(v: number | null | undefined, unit: string): string {
  if (v == null || Number.isNaN(v)) return "—";
  if (unit === "pct") return `${(v * 100).toFixed(1)}%`;
  if (unit === "usd") return `$${Math.round(v).toLocaleString()}`;
  if (unit === "x") return `${v.toFixed(2)}×`;
  return v.toFixed(2);
}

function deltaTone(points: number): string {
  if (points > 0) return "text-emerald-600 dark:text-emerald-400";
  if (points < 0) return "text-red-600 dark:text-red-400";
  return "text-muted-foreground";
}

export function ScoreChangeReport({ score }: { score: ScoreResponse }) {
  const [window, setWindow] = useState("previous");
  const body = useMemo(() => buildRequest(score, window), [score, window]);
  const q = useScoreChanges(body);
  const report = q.data;

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <CardTitle>What changed?</CardTitle>
            <CardDescription>
              Vs your own prior score — deterministic, not a benchmark.
            </CardDescription>
          </div>
          <div className="flex gap-1">
            {WINDOWS.map((w) => (
              <button
                key={w.key}
                type="button"
                onClick={() => {
                  setWindow(w.key);
                  track("score_change_window", { window: w.key });
                }}
                className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                  window === w.key
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted text-muted-foreground hover:bg-muted/70"
                }`}
              >
                {w.label}
              </button>
            ))}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {q.isLoading && <p className="text-sm text-muted-foreground">Comparing…</p>}

        {!q.isLoading && (!report || !report.available) && (
          <p className="text-sm text-muted-foreground">
            No earlier snapshot yet — a snapshot is saved each time you score, so
            your trend builds over time.
          </p>
        )}

        {!q.isLoading && report && report.available && (
          <>
            {/* headline: score delta + deterministic summary. When the prior
                snapshot used a different methodology version the delta is NOT a
                comparable move — suppress it and show a notice instead. */}
            <div className="flex items-baseline gap-3">
              <span className="text-sm text-muted-foreground">
                {report.previous_score} →
              </span>
              <span className="font-mono text-3xl font-semibold tabular-nums">
                {report.current_score}
              </span>
              {report.comparable !== false && (
                <span
                  className={`font-mono text-lg font-semibold ${deltaTone(
                    report.score_delta ?? 0,
                  )}`}
                >
                  {(report.score_delta ?? 0) >= 0 ? "+" : ""}
                  {report.score_delta}
                </span>
              )}
            </div>

            {report.comparable === false && (
              <div className="rounded-md border border-amber-300/60 bg-amber-50 p-2.5 text-sm dark:border-amber-500/30 dark:bg-amber-950/30">
                {/* A pre-versioning ("legacy") prior snapshot has UNKNOWN
                    provenance — don't claim the calculation changed (it may not
                    have). Only a genuine version-to-version change gets the
                    "methodology changed" wording. */}
                <p className="font-medium">
                  {report.previous_score_version &&
                  report.previous_score_version !== "legacy"
                    ? "Methodology changed; score delta is not directly comparable."
                    : "Not directly comparable to your earlier score (it predates methodology versioning)."}
                </p>
                {(report.previous_score_version || report.current_score_version) && (
                  <p className="mt-1 text-xs text-muted-foreground">
                    {report.previous_score_version ?? "unversioned"} →{" "}
                    {report.current_score_version ?? "current"} ·{" "}
                    <Link
                      href="/methodology/health-score"
                      className="text-primary hover:underline"
                    >
                      how the score is calculated
                    </Link>
                  </p>
                )}
              </div>
            )}

            <p className="text-sm leading-relaxed">{report.summary}</p>

            {/* top drivers — the exact per-dimension decomposition of the move */}
            {report.top_drivers.length > 0 && (
              <div className="space-y-1.5">
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  What moved the score
                </p>
                {report.top_drivers.map((d) => (
                  <div
                    key={d.key}
                    className="flex items-center justify-between gap-3 text-sm"
                  >
                    <span>{d.detail || d.label}</span>
                    <span className={`font-mono font-semibold ${deltaTone(d.points)}`}>
                      {d.points >= 0 ? "+" : ""}
                      {d.points} pts
                    </span>
                  </div>
                ))}
              </div>
            )}

            {/* data-quality changes — surfaced prominently (the bad-data case) */}
            {report.data_quality_changes.length > 0 && (
              <div className="rounded-md border border-amber-300/60 bg-amber-50 p-2.5 text-sm dark:border-amber-500/30 dark:bg-amber-950/30">
                {report.data_quality_changes.map((c) => (
                  <p key={c.key}>{c.note || `${c.label}: ${c.previous} → ${c.current}`}</p>
                ))}
              </div>
            )}

            {/* input metric changes */}
            {report.input_changes.length > 0 && (
              <details className="text-sm">
                <summary className="cursor-pointer text-muted-foreground">
                  The numbers that changed
                </summary>
                <div className="mt-2 space-y-1">
                  {report.input_changes.map((c) => (
                    <div key={c.key} className="flex items-center justify-between gap-3">
                      <span className="text-muted-foreground">{c.label}</span>
                      <span className="font-mono tabular-nums">
                        {fmt(c.previous, c.unit)} → {fmt(c.current, c.unit)}
                      </span>
                    </div>
                  ))}
                </div>
              </details>
            )}

            {/* holdings diff (when available) */}
            {(report.holdings_changes.added.length > 0 ||
              report.holdings_changes.removed.length > 0) && (
              <p className="text-xs text-muted-foreground">
                {report.holdings_changes.added.length > 0 &&
                  `Added: ${report.holdings_changes.added.join(", ")}. `}
                {report.holdings_changes.removed.length > 0 &&
                  `Removed: ${report.holdings_changes.removed.join(", ")}.`}
              </p>
            )}

            <p className="pt-1 text-xs text-muted-foreground">
              <Link href="/risk" className="text-primary hover:underline">
                See the full Risk Report →
              </Link>
            </p>
          </>
        )}
      </CardContent>
    </Card>
  );
}

/**
 * A prominent data-confidence pill. Shown only when confidence is NOT high (a
 * full-data book needs no caveat). Surfaces that a degraded-input score was
 * stabilized toward neutral rather than collapsing — the anti-silent-collapse UX.
 */
export function ConfidenceBadge({ metrics, baseOverall, overall }: {
  metrics: ScoreResponse["metrics"];
  baseOverall?: number | null;
  overall?: number;
}) {
  const confidence = metrics.confidence;
  if (!confidence || confidence === "high") return null;
  const dq = metrics.data_quality;
  const dropped = metrics.dropped_tickers ?? [];
  const stabilized =
    baseOverall != null && overall != null && Math.abs(baseOverall - overall) >= 5;
  const tone =
    confidence === "low"
      ? "border-red-300/60 bg-red-50 text-red-800 dark:border-red-500/30 dark:bg-red-950/30 dark:text-red-200"
      : "border-amber-300/60 bg-amber-50 text-amber-900 dark:border-amber-500/30 dark:bg-amber-950/30 dark:text-amber-200";
  return (
    <div className={`rounded-md border p-2.5 text-sm ${tone}`}>
      <span className="font-semibold capitalize">{confidence} data confidence</span>
      {typeof dq === "number" ? ` (${Math.round(dq * 100)}%)` : ""} —{" "}
      {stabilized
        ? `this score is stabilized toward neutral (raw ${baseOverall}) until the data improves`
        : "some inputs are degraded"}
      {dropped.length > 0 ? `; missing price data for ${dropped.join(", ")}` : ""}.
    </div>
  );
}

/**
 * The structured, deterministic reason codes behind the score (the LLM may
 * phrase these elsewhere, but these come straight from the engine). Renders
 * nothing when there are no material penalties.
 */
export function ReasonCodes({ score }: { score: ScoreResponse }) {
  const codes = (score.reason_codes ?? []).filter(
    (r) => r.code !== "low_data_confidence", // already shown by ConfidenceBadge
  );
  if (codes.length === 0) return null;
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle>Why this score</CardTitle>
        <CardDescription>Deterministic reasons — computed, not AI-written.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-1.5">
        {codes.map((r, i) => (
          <div key={`${r.code}-${i}`} className="flex items-start gap-2 text-sm">
            <span
              className={`mt-0.5 inline-block h-2 w-2 shrink-0 rounded-full ${
                r.severity === "high" ? "bg-red-500" : "bg-amber-500"
              }`}
            />
            <span>{r.detail || r.code}</span>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
