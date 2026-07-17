"use client";

/**
 * <DataConfidence> — the ONE way the whole app shows how much to trust a
 * conclusion. Renders the unified backend contract (schemas/confidence.py →
 * dataConfidenceSchema): a High / Medium / Low badge, freshness, which critical
 * datasets are missing and WHY, how that caps the conclusion, and an expandable
 * per-source breakdown. Used on score, risk report, research and Copilot so the
 * "truthfulness" story is identical everywhere.
 *
 * Design tokens only (Badge tones + the house pill style + tabular-nums) — no
 * new palette. Pure presentation; every number comes from the backend.
 */

import { useState } from "react";
import type { DataConfidence, FieldProvenance } from "@/lib/schemas";
import { Badge, type BadgeTone } from "@/components/ui/badge";

const LABEL_TONE: Record<DataConfidence["label"], BadgeTone> = {
  high: "success",
  medium: "warning",
  low: "danger",
};

const LABEL_TEXT: Record<DataConfidence["label"], string> = {
  high: "High confidence",
  medium: "Medium confidence",
  low: "Low confidence",
};

const SOURCE_TYPE_TONE: Record<string, BadgeTone> = {
  primary: "primary",
  secondary: "warning",
  derived: "neutral",
};

const SOURCE_TYPE_TEXT: Record<string, string> = {
  primary: "primary",
  secondary: "fallback",
  derived: "derived / estimate",
};

// The typed missing-reason enum → plain English (rule #4 distinctions).
const MISSING_REASON: Record<string, string> = {
  no_key: "source credential unavailable — using public fallback data",
  provider_error: "provider error",
  rate_limited: "rate limited",
  insufficient_history: "not enough history",
  not_applicable: "not applicable",
  stale_fallback: "stale (served from cache)",
  synthetic_demo: "illustrative synthetic data — not market history",
  unsupported: "not supported by the current source",
  empty: "no data returned",
};

const pct = (x: number | null | undefined) =>
  x == null ? "—" : `${Math.round(Math.max(0, Math.min(1, x)) * 100)}%`;

function reasonLabel(m?: string | null): string {
  return (m && MISSING_REASON[m]) || m || "unavailable";
}

export function DataConfidence({
  confidence,
  className,
  title = "Data confidence",
}: {
  confidence: DataConfidence | null | undefined;
  className?: string;
  title?: string;
}) {
  const [open, setOpen] = useState(false);
  if (!confidence) return null;
  const dc = confidence;
  const missing = (dc.missing ?? []).filter((m) => (m.coverage ?? 0) < 1);
  const capReasons = (dc.reason_codes ?? []).filter((r) => r.detail);
  const directionalBlocked = dc.directional_allowed === false;

  return (
    <section
      className={`rounded-lg border border-border bg-card/40 p-3 text-[13px] ${className ?? ""}`}
      aria-label={title}
    >
      {/* header: label + coverage + freshness */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          {title}
        </span>
        <Badge tone={LABEL_TONE[dc.label]}>
          {LABEL_TEXT[dc.label]} · {pct(dc.confidence)}
        </Badge>
        <span className="text-muted-foreground tabular-nums">
          critical coverage {pct(dc.critical_coverage)} · overall {pct(dc.overall_coverage)}
        </span>
        {dc.stale ? <Badge tone="warning">stale</Badge> : null}
        {dc.fallback_used ? <Badge tone="warning">fallback</Badge> : null}
        {dc.cross_source_agreement != null ? (
          <span className="text-muted-foreground tabular-nums">
            cross-source agreement {pct(dc.cross_source_agreement)}
          </span>
        ) : null}
        {dc.as_of ? (
          <span className="text-muted-foreground">as of {dc.as_of}</span>
        ) : null}
      </div>

      {/* the enforcement banner — "how missing data affects the conclusion" */}
      {directionalBlocked ? (
        <p className="mt-2 rounded-md border border-destructive/40 bg-destructive/10 px-2.5 py-1.5 text-destructive">
          Not enough data for a directional read — treat this as informational
          context, not a conclusion.
        </p>
      ) : dc.conviction_cap && dc.conviction_cap !== "high" ? (
        <p className="mt-2 text-muted-foreground">
          Conviction capped at <b>{dc.conviction_cap}</b> by data quality.
        </p>
      ) : null}

      {/* why — the reason codes */}
      {capReasons.length > 0 ? (
        <ul className="mt-1.5 space-y-0.5 text-muted-foreground">
          {capReasons.slice(0, 4).map((r, i) => (
            <li key={`${r.code}-${i}`} className="flex gap-1.5">
              <span
                aria-hidden
                className={`mt-1 h-1.5 w-1.5 shrink-0 rounded-full ${
                  r.severity === "high" ? "bg-destructive" : "bg-[hsl(var(--warning))]"
                }`}
              />
              <span>{r.detail}</span>
            </li>
          ))}
        </ul>
      ) : null}

      {/* missing critical datasets */}
      {missing.length > 0 ? (
        <p className="mt-1.5 text-muted-foreground">
          <span className="font-medium text-foreground">Missing:</span>{" "}
          {missing
            .slice(0, 6)
            .map((m) => `${m.field} (${reasonLabel(m.missing_reason)})`)
            .join(", ")}
          {missing.length > 6 ? ` +${missing.length - 6} more` : ""}
        </p>
      ) : null}

      {/* expandable per-source detail */}
      {(dc.sources ?? []).length > 0 ? (
        <div className="mt-2">
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground hover:text-foreground"
            aria-expanded={open}
          >
            {open ? "Hide" : "Show"} source details ({(dc.sources ?? []).length})
          </button>
          {open ? (
            <div className="mt-1.5 overflow-x-auto">
              <table className="w-full min-w-[380px] text-[12px]">
                <thead>
                  <tr className="text-left text-[10px] uppercase tracking-wide text-muted-foreground">
                    <th className="py-1 pr-3 font-medium">Field</th>
                    <th className="py-1 pr-3 font-medium">Source</th>
                    <th className="py-1 pr-3 font-medium">Type</th>
                    <th className="py-1 pr-3 text-right font-medium">Coverage</th>
                    <th className="py-1 font-medium">As of</th>
                  </tr>
                </thead>
                <tbody>
                  {(dc.sources ?? []).map((s: FieldProvenance, i) => (
                    <tr key={`${s.field}-${i}`} className="border-t border-border/50">
                      <td className="py-1 pr-3">{s.field}</td>
                      <td className="py-1 pr-3">{s.label || s.source}</td>
                      <td className="py-1 pr-3">
                        <Badge tone={SOURCE_TYPE_TONE[s.source_type ?? "derived"] ?? "neutral"}>
                          {SOURCE_TYPE_TEXT[s.source_type ?? "derived"] ?? s.source_type}
                        </Badge>
                        {s.fallback_used ? (
                          <span className="ml-1 text-[10px] text-[hsl(var(--warning))]">
                            fallback
                          </span>
                        ) : null}
                      </td>
                      <td className="py-1 pr-3 text-right tabular-nums">{pct(s.coverage)}</td>
                      <td className="py-1 text-muted-foreground">{s.as_of || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
