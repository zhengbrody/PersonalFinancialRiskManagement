/**
 * Server-safe (no hooks) prose readout of the composed market risk read, fed by
 * /api/v1/regime/summary. Rendered in the SSR body of /risk-today so Google + a
 * social unfurl get real text, not a hydration skeleton.
 *
 * Honest framing (matches the model card): the PRIMARY output is the validated
 * elevated-risk PROBABILITY, not the 4-class label (on 4-class accuracy the model
 * loses to a persistence baseline). When the backend degrades (model inactive /
 * stale data / drift), we show deterministic market context only — no probability.
 */

import Link from "next/link";
import { C, display } from "@/components/marketing/theme";

export type RegimeSummary = {
  headline: string;
  elevated_risk_probability: number | null;
  probability_band: string | null;
  regime_state: string | null;
  label: string | null;
  blurb: string | null;
  confidence: number | null;
  drivers: { label: string; vs_normal: string }[];
  vix: { current: number | null; change: number | null; level: string | null };
  fear_greed: { score: number | null; rating: string | null };
  curve: { status: string | null; spread_3m_10y: number | null; inverted: boolean | null };
  as_of: string | null;
  source: string;
  model_version: string | null;
  health_status: string | null;
  degraded: boolean;
  degraded_reason: string | null;
  caveat: string;
  post_text: string;
};

const BAND_COLOR: Record<string, string> = {
  Low: C.up,
  Moderate: C.teal,
  High: C.gold,
  "Very high": C.down,
};

const DEGRADED_REASON: Record<string, string> = {
  model_unavailable: "the risk-state model is temporarily unavailable",
  stale_data: "the latest market data looks stale",
  model_drift: "the model is drifting from its training data",
};

function degradedReasonText(reason: string | null): string {
  if (!reason) return "the model signal isn't available right now";
  return DEGRADED_REASON[reason] ?? "the model isn't healthy right now";
}

function provenance(r: RegimeSummary): string {
  const bits: string[] = [];
  if (r.source === "model") bits.push(`model ${r.model_version ?? "regime"}`);
  else if (r.source === "heuristic_fallback") bits.push("current-vol estimate · model unavailable");
  else bits.push("market data");
  if (r.as_of) bits.push(`data as of ${r.as_of}`);
  if (r.health_status) bits.push(`drift check: ${r.health_status}`);
  return bits.join(" · ");
}

function MacroStat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div
      style={{
        flex: "1 1 130px",
        padding: "14px 16px",
        borderRadius: 12,
        background: C.surfaceFaint,
        border: `1px solid ${C.hair}`,
      }}
    >
      <div style={{ color: C.slateDim, fontSize: 11, textTransform: "uppercase", letterSpacing: ".12em" }}>
        {label}
      </div>
      <div style={{ ...display, color: C.paper, fontSize: 26, marginTop: 4 }}>{value}</div>
      {sub && <div style={{ color: C.slate, fontSize: 12, marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

export function RegimeReadout({ summary }: { summary: RegimeSummary }) {
  const showProb = !summary.degraded && summary.elevated_risk_probability != null;
  const bandColor = summary.probability_band
    ? BAND_COLOR[summary.probability_band] ?? C.teal
    : C.slate;

  const vix = summary.vix.current != null ? summary.vix.current.toFixed(1) : "—";
  const vixSub =
    summary.vix.change != null
      ? `${summary.vix.change >= 0 ? "+" : ""}${summary.vix.change.toFixed(1)} today`
      : summary.vix.level ?? undefined;

  return (
    <section style={{ display: "flex", flexDirection: "column", gap: 22 }}>
      {/* headline */}
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 14 }}>
        <h1 style={{ ...display, color: C.paper, fontSize: "clamp(30px,4.5vw,48px)", fontWeight: 400, margin: 0, lineHeight: 1.06 }}>
          {summary.headline}
        </h1>
        {showProb && summary.probability_band && (
          <span
            style={{
              padding: "8px 18px",
              borderRadius: 999,
              background: `${bandColor}22`,
              color: bandColor,
              fontSize: 18,
              fontWeight: 700,
            }}
          >
            {summary.probability_band}
          </span>
        )}
      </div>

      {/* what the probability means (only when shown) */}
      {showProb && (
        <p style={{ color: C.slate, fontSize: 18, lineHeight: 1.6, margin: 0, maxWidth: "46em" }}>
          The model&apos;s estimated probability that the next ~2 weeks bring an
          elevated-risk (higher-volatility) environment. This is a{" "}
          <strong style={{ color: C.paper }}>probability-ranking signal</strong>, not a
          forecast of prices or returns.
        </p>
      )}

      {/* degraded note — deterministic market context only */}
      {summary.degraded && (
        <div
          style={{
            borderRadius: 12,
            border: `1px solid ${C.hair}`,
            background: C.surfaceFaint,
            padding: "14px 16px",
            color: C.slate,
            fontSize: 15,
            lineHeight: 1.6,
          }}
        >
          Showing deterministic market data only — {degradedReasonText(summary.degraded_reason)}.
          The model&apos;s probability signal isn&apos;t shown while that&apos;s the case.
        </div>
      )}

      {/* macro stats (always) */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
        <MacroStat label="VIX" value={vix} sub={vixSub} />
        <MacroStat
          label="Fear & Greed"
          value={summary.fear_greed.score != null ? summary.fear_greed.score.toFixed(0) : "—"}
          sub={summary.fear_greed.rating ?? undefined}
        />
        <MacroStat
          label="Yield curve"
          value={summary.curve.status ?? "—"}
          sub={
            summary.curve.spread_3m_10y != null
              ? `3M–10Y ${summary.curve.spread_3m_10y >= 0 ? "+" : ""}${summary.curve.spread_3m_10y.toFixed(2)}`
              : undefined
          }
        />
      </div>

      {/* secondary: the 4-class label (context only, never the headline) */}
      {showProb && summary.label && (
        <p style={{ color: C.slateDim, fontSize: 14, margin: 0 }}>
          Secondary context — the model&apos;s 4-class read is{" "}
          <strong style={{ color: C.slate }}>{summary.label}</strong>
          {summary.blurb ? `. ${summary.blurb}` : "."} The 4-class label is context
          only; its accuracy does not beat a naive persistence baseline.
        </p>
      )}

      {/* drivers (only when the probability is shown) */}
      {showProb && summary.drivers.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <p style={{ color: C.slateDim, fontSize: 12, textTransform: "uppercase", letterSpacing: ".14em", margin: 0 }}>
            What the model is weighing
          </p>
          {summary.drivers.map((d) => (
            <div
              key={d.label}
              style={{ display: "flex", justifyContent: "space-between", gap: 12, color: C.paper, fontSize: 15 }}
            >
              <span>{d.label}</span>
              <span style={{ color: C.slate }}>{d.vs_normal}</span>
            </div>
          ))}
        </div>
      )}

      {/* method note — prominent, concise, honest */}
      <div
        style={{
          borderRadius: 12,
          border: `1px solid ${C.gold}44`,
          background: `${C.gold}0F`,
          padding: "14px 16px",
        }}
      >
        <p style={{ color: C.paper, fontSize: 13, fontWeight: 600, margin: "0 0 6px", textTransform: "uppercase", letterSpacing: ".08em" }}>
          How to read this
        </p>
        <p style={{ color: C.slate, fontSize: 14, lineHeight: 1.6, margin: 0 }}>
          An <strong style={{ color: C.paper }}>experimental probability-ranking signal</strong>. It
          does <strong style={{ color: C.paper }}>not</strong> predict prices or returns, and on
          4-class regime accuracy it does <strong style={{ color: C.paper }}>not</strong> beat a
          persistence baseline. Its validated value is ranking elevated-risk probability.{" "}
          <Link href="/methodology/regime-model" style={{ color: C.teal, textDecoration: "none" }}>
            Read the model card →
          </Link>
        </p>
      </div>

      {/* provenance + caveat */}
      <p style={{ color: C.slateDim, fontSize: 13, lineHeight: 1.6, margin: 0, borderTop: `1px solid ${C.hair}`, paddingTop: 14 }}>
        {summary.caveat} <span style={{ opacity: 0.8 }}>Source: {provenance(summary)}.</span>
      </p>
    </section>
  );
}
