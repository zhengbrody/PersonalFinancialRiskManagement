/**
 * Server-safe (no hooks) prose readout of the composed market risk-state, fed by
 * /api/v1/regime/summary. Rendered in the SSR body of /risk-today so Google + a
 * social unfurl get real text (headline + drivers + provenance), not a hydration
 * skeleton. Every number is deterministic from the backend; the caveat is the
 * backend's canonical no-advice string.
 */

import { C, display } from "@/components/marketing/theme";

export type RegimeSummary = {
  headline: string;
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
  caveat: string;
  post_text: string;
};

const STATE_COLOR: Record<string, string> = {
  risk_on: C.up,
  neutral: C.teal,
  volatile: C.gold,
  stress: C.down,
};

function provenance(r: RegimeSummary): string {
  if (r.source === "unavailable") return "market data unavailable";
  if (r.source === "heuristic_fallback")
    return `current-vol estimate · model unavailable${r.as_of ? ` · as of ${r.as_of}` : ""}`;
  return `model ${r.model_version ?? "regime"}${r.as_of ? ` · as of ${r.as_of}` : ""}`;
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
  const accent = summary.regime_state ? STATE_COLOR[summary.regime_state] ?? C.teal : C.slate;
  const conf = summary.confidence != null ? `${Math.round(summary.confidence * 100)}%` : null;
  const vix = summary.vix.current != null
    ? summary.vix.current.toFixed(1)
    : "—";
  const vixSub =
    summary.vix.change != null
      ? `${summary.vix.change >= 0 ? "+" : ""}${summary.vix.change.toFixed(1)} today`
      : summary.vix.level ?? undefined;

  return (
    <section style={{ display: "flex", flexDirection: "column", gap: 22 }}>
      {/* headline + state */}
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 14 }}>
        <h1 style={{ ...display, color: C.paper, fontSize: "clamp(34px,5vw,52px)", fontWeight: 400, margin: 0, lineHeight: 1.05 }}>
          {summary.headline}
        </h1>
        {summary.label && (
          <span
            style={{
              padding: "8px 18px",
              borderRadius: 999,
              background: `${accent}22`,
              color: accent,
              fontSize: 18,
              fontWeight: 700,
            }}
          >
            {summary.label}
            {conf ? ` · ${conf}` : ""}
          </span>
        )}
      </div>

      {summary.blurb && (
        <p style={{ color: C.slate, fontSize: 18, lineHeight: 1.6, margin: 0, maxWidth: "44em" }}>
          {summary.blurb}
        </p>
      )}

      {/* macro stats */}
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

      {/* drivers */}
      {summary.drivers.length > 0 && (
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

      {/* provenance + caveat */}
      <p style={{ color: C.slateDim, fontSize: 13, lineHeight: 1.6, margin: 0, borderTop: `1px solid ${C.hair}`, paddingTop: 14 }}>
        {summary.caveat} <span style={{ opacity: 0.8 }}>Source: {provenance(summary)}.</span>
      </p>
    </section>
  );
}
