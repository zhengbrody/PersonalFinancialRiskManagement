/**
 * /methodology/regime-model — the PUBLIC model card for the market risk-state
 * classifier. Server-rendered; every number is fetched from the backend, which
 * reads them straight from the committed ML artifacts (regime_meta.json +
 * validation_report.json) — so the page can never drift from what validated the
 * model. Honest by construction: it leads with "loses to persistence on 4-class,
 * value is the elevated-risk probability".
 */

import type { Metadata } from "next";
import Link from "next/link";
import { MarketingShell } from "@/components/marketing/marketing-shell";
import { C, display } from "@/components/marketing/theme";
import { CTA, Disclaimer } from "@/components/marketing/primitives";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://mindmarket.app";

// Force per-request SSR: the metrics come from the backend, which isn't up at
// build time (same reason as /risk-today). The backend reads static committed
// JSON, so this is cheap.
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Risk-state model card — honest validation metrics",
  description:
    "The model card for MindMarket's market risk-state classifier: what it is (an experimental elevated-risk probability signal), its honest validation metrics — 4-class accuracy vs a persistence baseline, elevated-risk ROC-AUC, Brier score, calibration — its features, and its limitations. Not a price or return forecast.",
  alternates: { canonical: "/methodology/regime-model" },
  openGraph: {
    type: "article",
    title: "Risk-state model card | MindMarket",
    description:
      "Honest, artifact-sourced validation metrics for the market risk-state classifier — a probability-ranking signal, not a classifier and not a forecast.",
    url: `${SITE_URL}/methodology/regime-model`,
    siteName: "mindmarket.app",
    images: ["/og.jpg?v=3"],
  },
  twitter: { card: "summary_large_image" },
};

type Feature = { name: string; importance: number | null };
type CalibrationBin = {
  bin: string;
  n: number;
  mean_predicted: number | null;
  observed_frequency: number | null;
};
type ClassDefinition = { label: string; key: string; definition: string };

type ModelCard = {
  available: boolean;
  model_version: string | null;
  trained_at: string | null;
  sklearn_version: string | null;
  estimator: string | null;
  headline: string;
  intended_use: string;
  not_for: string[];
  limitations: string[];
  excluded_signals: string;
  classes: string[];
  class_definitions: ClassDefinition[];
  features: Feature[];
  training_window: { start?: string; end?: string; rows?: number };
  class_distribution: Record<string, number>;
  cv_accuracy: number | null;
  persistence_baseline_accuracy: number | null;
  majority_baseline_cv_accuracy: number | null;
  holdout_accuracy: number | null;
  holdout_majority_baseline_accuracy: number | null;
  elevated_risk_auc: number | null;
  brier: number | null;
  brier_base_rate: number | null;
  elevated_base_rate: number | null;
  holdout_size: number | null;
  calibration_bins: CalibrationBin[];
};

async function fetchModelCard(): Promise<ModelCard | null> {
  const base = process.env.INTERNAL_API_BASE_URL || "http://backend:8000";
  try {
    const res = await fetch(`${base}/api/v1/ml/model_card`, { cache: "no-store" });
    if (!res.ok) return null;
    const body = (await res.json()) as { data?: ModelCard };
    return body?.data ?? null;
  } catch {
    return null;
  }
}

const num = (x: number | null | undefined, d = 3) => (x == null ? "—" : x.toFixed(d));
const pct = (x: number | null | undefined, d = 1) => (x == null ? "—" : `${(x * 100).toFixed(d)}%`);

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section style={{ marginTop: 40 }}>
      <h2 style={{ ...display, fontSize: 26, letterSpacing: "-0.01em", margin: "0 0 12px" }}>{title}</h2>
      <div style={{ fontSize: 16, lineHeight: 1.7, color: C.slate }}>{children}</div>
    </section>
  );
}

const cell: React.CSSProperties = {
  padding: "10px 12px",
  borderBottom: `1px solid ${C.hair}`,
  textAlign: "left",
  verticalAlign: "top",
};
const th: React.CSSProperties = {
  ...cell,
  color: C.paper,
  fontSize: 12,
  fontWeight: 600,
  textTransform: "uppercase",
  letterSpacing: ".08em",
};
const mono: React.CSSProperties = { ...cell, fontFamily: "ui-monospace, monospace" };

export default async function RegimeModelCardPage() {
  const card = await fetchModelCard();

  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "TechArticle",
    headline: "Market risk-state model card",
    description:
      "Honest, artifact-sourced validation metrics for the market risk-state classifier — an experimental elevated-risk probability signal, not a classifier and not a forecast.",
    url: `${SITE_URL}/methodology/regime-model`,
    ...(card?.model_version ? { version: card.model_version } : {}),
  };

  return (
    <MarketingShell>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />
      <article style={{ maxWidth: 820, margin: "0 auto", padding: "120px 24px 56px" }}>
        <nav style={{ fontSize: 13, color: C.slateDim, marginBottom: 18 }}>
          <Link href="/risk-today" style={{ color: C.teal, textDecoration: "none" }}>
            Risk today
          </Link>{" "}
          / Model card
        </nav>

        <header>
          <p style={{ fontSize: 12, fontWeight: 600, textTransform: "uppercase", letterSpacing: ".12em", color: C.teal, margin: 0 }}>
            Model card
          </p>
          <h1 style={{ ...display, fontSize: 40, lineHeight: 1.1, margin: "8px 0 10px" }}>
            Market risk-state model
          </h1>
          {card?.model_version && (
            <p style={{ fontSize: 13, color: C.slateDim, margin: "0 0 8px", fontFamily: "ui-monospace, monospace" }}>
              {card.model_version}
              {card.trained_at ? ` · trained ${String(card.trained_at).slice(0, 10)}` : ""}
              {card.estimator ? ` · ${card.estimator}` : ""}
            </p>
          )}
          <p style={{ fontSize: 18, lineHeight: 1.65, color: C.slate, maxWidth: "44em" }}>
            {card?.headline ??
              "An experimental probability-ranking signal for elevated market-risk pressure — not a price or return forecast. Metrics are temporarily unavailable."}
          </p>
        </header>

        {!card?.available && (
          <p style={{ marginTop: 20, color: C.slateDim, fontSize: 14 }}>
            The live metrics are temporarily unavailable; the description below still applies.
          </p>
        )}

        <Section title="What it is — and isn’t">
          <p>{card?.intended_use}</p>
          {card?.not_for && card.not_for.length > 0 && (
            <ul style={{ paddingLeft: 20, margin: "12px 0 0" }}>
              {card.not_for.map((n) => (
                <li key={n} style={{ marginTop: 6 }}>
                  <strong style={{ color: C.paper }}>Not</strong> {n}
                </li>
              ))}
            </ul>
          )}
        </Section>

        <Section title="Honest validation metrics">
          <p>
            On 4-class accuracy the model <Em>loses</Em> to a naive persistence baseline. The skill
            that survives honest walk-forward validation is the calibrated elevated-risk
            probability. These numbers are read directly from the committed model artifacts.
          </p>
          <div style={{ overflowX: "auto", margin: "16px 0" }}>
            <table style={{ borderCollapse: "collapse", width: "100%", minWidth: 460 }}>
              <thead>
                <tr>
                  <th style={th}>Metric</th>
                  <th style={th}>Value</th>
                  <th style={th}>Reference</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td style={cell}>4-class accuracy (walk-forward)</td>
                  <td style={mono}>{num(card?.cv_accuracy)}</td>
                  <td style={cell}>
                    persistence <span style={{ fontFamily: "ui-monospace, monospace", color: C.paper }}>{num(card?.persistence_baseline_accuracy)}</span> · majority{" "}
                    <span style={{ fontFamily: "ui-monospace, monospace" }}>{num(card?.majority_baseline_cv_accuracy)}</span>
                  </td>
                </tr>
                <tr>
                  <td style={cell}>4-class accuracy (hold-out)</td>
                  <td style={mono}>{num(card?.holdout_accuracy)}</td>
                  <td style={cell}>
                    majority <span style={{ fontFamily: "ui-monospace, monospace" }}>{num(card?.holdout_majority_baseline_accuracy)}</span>
                  </td>
                </tr>
                <tr>
                  <td style={{ ...cell, color: C.paper, fontWeight: 600 }}>Elevated-risk ROC-AUC (the signal)</td>
                  <td style={{ ...mono, color: C.paper, fontWeight: 600 }}>{num(card?.elevated_risk_auc)}</td>
                  <td style={cell}>binary volatile ∪ stress</td>
                </tr>
                <tr>
                  <td style={cell}>Brier score (elevated-risk prob.)</td>
                  <td style={mono}>{num(card?.brier, 4)}</td>
                  <td style={cell}>
                    base-rate reference <span style={{ fontFamily: "ui-monospace, monospace" }}>{num(card?.brier_base_rate, 4)}</span>
                  </td>
                </tr>
                <tr>
                  <td style={cell}>Hold-out size · elevated base rate</td>
                  <td style={mono}>{card?.holdout_size ?? "—"}</td>
                  <td style={cell}>{pct(card?.elevated_base_rate)}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </Section>

        {card?.calibration_bins && card.calibration_bins.length > 0 && (
          <Section title="Calibration (hold-out)">
            <p>Predicted elevated-risk probability vs. what actually happened, in deciles.</p>
            <div style={{ overflowX: "auto", margin: "16px 0" }}>
              <table style={{ borderCollapse: "collapse", width: "100%", minWidth: 420 }}>
                <thead>
                  <tr>
                    <th style={th}>Predicted bin</th>
                    <th style={th}>n</th>
                    <th style={th}>Mean predicted</th>
                    <th style={th}>Observed freq.</th>
                  </tr>
                </thead>
                <tbody>
                  {card.calibration_bins.map((b) => (
                    <tr key={b.bin}>
                      <td style={mono}>{b.bin}</td>
                      <td style={mono}>{b.n}</td>
                      <td style={mono}>{num(b.mean_predicted, 3)}</td>
                      <td style={mono}>{num(b.observed_frequency, 3)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>
        )}

        {card?.class_definitions && card.class_definitions.length > 0 && (
          <Section title="What the 4 classes mean (secondary context)">
            <ul style={{ paddingLeft: 20, margin: 0 }}>
              {card.class_definitions.map((c) => (
                <li key={c.key} style={{ marginTop: 6 }}>
                  <strong style={{ color: C.paper }}>{c.label}</strong> — {c.definition}.
                </li>
              ))}
            </ul>
          </Section>
        )}

        {card?.features && card.features.length > 0 && (
          <Section title="Inputs (most important first)">
            <p style={{ fontFamily: "ui-monospace, monospace", fontSize: 13, color: C.paper }}>
              {card.features.map((f) => f.name).join(" · ")}
            </p>
            <p style={{ fontSize: 14, marginTop: 8 }}>{card.excluded_signals}</p>
          </Section>
        )}

        {card?.training_window?.rows && (
          <Section title="Training data">
            <p>
              Free daily market history, {card.training_window.start} → {card.training_window.end} (
              {card.training_window.rows.toLocaleString()} labeled rows). Class distribution:{" "}
              {Object.entries(card.class_distribution || {})
                .map(([k, v]) => `${k} ${v}`)
                .join(" · ")}
              .
            </p>
          </Section>
        )}

        {card?.limitations && card.limitations.length > 0 && (
          <Section title="Limitations">
            <ul style={{ paddingLeft: 20, margin: 0 }}>
              {card.limitations.map((l) => (
                <li key={l} style={{ marginTop: 6 }}>
                  {l}
                </li>
              ))}
            </ul>
          </Section>
        )}

        <div style={{ display: "flex", gap: 14, flexWrap: "wrap", margin: "40px 0 22px" }}>
          <CTA href="/risk-today" lg>
            See today’s read
          </CTA>
          <CTA href="/methodology/health-score" variant="ghost" lg>
            Health Score methodology
          </CTA>
        </div>
        <Disclaimer>
          Educational market context only — not a price or return forecast, and not investment
          advice. This signal never changes your Health Score or any deterministic risk number.
        </Disclaimer>
      </article>
    </MarketingShell>
  );
}

function Em({ children }: { children: React.ReactNode }) {
  return <span style={{ color: C.gold, fontStyle: "italic" }}>{children}</span>;
}
