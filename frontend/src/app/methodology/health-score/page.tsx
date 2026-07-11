/**
 * /methodology/health-score — the public, auditable methodology page.
 *
 * Server component (SSR/SEO) wearing the marketing shell. Every parameter here
 * MIRRORS the backend single source of truth (libs/mindmarket_core). It is
 * documentation only — no math runs here. Deliberately avoids the phrase
 * "industry standard score": the score is our own transparent construction, and
 * we say exactly how it is built.
 */

import type { Metadata } from "next";
import Link from "next/link";
import { MarketingShell } from "@/components/marketing/marketing-shell";
import { C, display } from "@/components/marketing/theme";
import { CTA, Disclaimer } from "@/components/marketing/primitives";
import {
  DIMENSIONS,
  PARAMETERS,
  RISK_TARGETS,
  SCORE_CHANGELOG,
  SCORE_METHODOLOGY_VERSION,
} from "@/lib/score-methodology";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://mindmarket.app";

export const metadata: Metadata = {
  title: "How the Health Score is calculated — methodology & version",
  description:
    "The exact, auditable methodology behind MindMarket's 0–1000 Portfolio Health Score: the three dimensions and weights, how your risk preference sets the target, the history window, benchmark, risk-free rate, the two kinds of Value-at-Risk, leverage/cash/options handling, missing-data stabilization, and its limitations.",
  alternates: { canonical: "/methodology/health-score" },
  openGraph: {
    type: "article",
    title: "How the MindMarket Health Score is calculated",
    description:
      "A transparent, versioned methodology for a 0–1000 portfolio Health Score — dimensions, weights, VaR, benchmark, risk-free rate, stabilization, and limitations.",
    url: `${SITE_URL}/methodology/health-score`,
    siteName: "mindmarket.app",
    images: ["/og.jpg?v=3"],
  },
  twitter: { card: "summary_large_image" },
};

const pct = (x: number) => `${(x * 100).toFixed(0)}%`;

const breadcrumbLd = {
  "@context": "https://schema.org",
  "@type": "BreadcrumbList",
  itemListElement: [
    { "@type": "ListItem", position: 1, name: "Home", item: SITE_URL },
    {
      "@type": "ListItem",
      position: 2,
      name: "Health Score methodology",
      item: `${SITE_URL}/methodology/health-score`,
    },
  ],
};

const articleLd = {
  "@context": "https://schema.org",
  "@type": "TechArticle",
  headline: "How the MindMarket Health Score is calculated",
  description:
    "The auditable, versioned methodology behind the 0–1000 Portfolio Health Score.",
  version: SCORE_METHODOLOGY_VERSION,
  url: `${SITE_URL}/methodology/health-score`,
};

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section style={{ marginTop: 40 }}>
      <h2 style={{ ...display, fontSize: 26, letterSpacing: "-0.01em", margin: "0 0 12px" }}>
        {title}
      </h2>
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

export default function HealthScoreMethodologyPage() {
  return (
    <MarketingShell>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(breadcrumbLd) }}
      />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(articleLd) }}
      />

      <article style={{ maxWidth: 820, margin: "0 auto", padding: "120px 24px 56px" }}>
        <nav style={{ fontSize: 13, color: C.slateDim, marginBottom: 18 }}>
          <Link href="/" style={{ color: C.teal, textDecoration: "none" }}>
            Home
          </Link>{" "}
          / Health Score methodology
        </nav>

        <header>
          <p
            style={{
              fontSize: 12,
              fontWeight: 600,
              textTransform: "uppercase",
              letterSpacing: ".12em",
              color: C.teal,
              margin: 0,
            }}
          >
            Methodology
          </p>
          <h1 style={{ ...display, fontSize: 40, lineHeight: 1.1, margin: "8px 0 10px" }}>
            How the Health Score is calculated
          </h1>
          <p style={{ fontSize: 13, ...display, color: C.slateDim, margin: "0 0 6px" }}>
            Version{" "}
            <span style={{ fontFamily: "var(--font-mono, ui-monospace, monospace)" }}>
              {SCORE_METHODOLOGY_VERSION}
            </span>
          </p>
          <p style={{ fontSize: 18, lineHeight: 1.65, color: C.slate, maxWidth: "42em" }}>
            The Portfolio Health Score is a 0–1000 number we build ourselves from your
            holdings — not a rating we buy or borrow. Every input is computed
            deterministically from market data; this page states exactly how, so you can
            audit the number and know when two scores are (and aren&apos;t) comparable.
          </p>
        </header>

        <Section title="The three dimensions and their weights">
          <p>
            The score is a weighted blend of three 0–10 dimension scores. Each measures a
            different, independent facet of portfolio risk:
          </p>
          <div style={{ overflowX: "auto", margin: "16px 0" }}>
            <table style={{ borderCollapse: "collapse", width: "100%", minWidth: 520 }}>
              <thead>
                <tr>
                  <th style={th}>Dimension</th>
                  <th style={th}>Weight</th>
                  <th style={th}>What it measures</th>
                </tr>
              </thead>
              <tbody>
                {DIMENSIONS.map((d) => (
                  <tr key={d.name}>
                    <td style={{ ...cell, color: C.paper, fontWeight: 600 }}>{d.name}</td>
                    <td style={{ ...cell, fontFamily: "ui-monospace, monospace" }}>
                      {pct(d.weight)}
                    </td>
                    <td style={cell}>{d.blurb}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p>
            The three 0–10 dimension scores are weighted (0.35 / 0.35 / 0.30), then mapped
            onto the 0–1000 scale: a weighted 1/10 lands near 0 and a weighted 10/10 lands
            at 1000. Only the overall score is on the 0–1000 scale; each dimension is 0–10.
          </p>
        </Section>

        <Section title="Your risk preference sets the target">
          <p>
            &quot;Risk Match&quot; is scored against a target for the risk level you choose (1–5).
            Each level has a target annualized volatility and market beta; the further your
            book sits from its target band (volatility weighted 65%, beta 35%), the lower
            this dimension:
          </p>
          <div style={{ overflowX: "auto", margin: "16px 0" }}>
            <table style={{ borderCollapse: "collapse", width: "100%", minWidth: 480 }}>
              <thead>
                <tr>
                  <th style={th}>Preference</th>
                  <th style={th}>Target volatility</th>
                  <th style={th}>Target beta</th>
                </tr>
              </thead>
              <tbody>
                {RISK_TARGETS.map((t) => (
                  <tr key={t.pref}>
                    <td style={{ ...cell, color: C.paper }}>
                      {t.pref} · {t.label}
                    </td>
                    <td style={{ ...cell, fontFamily: "ui-monospace, monospace" }}>{pct(t.vol)}</td>
                    <td style={{ ...cell, fontFamily: "ui-monospace, monospace" }}>
                      {t.beta.toFixed(2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>

        <Section title="History window, benchmark and risk-free rate">
          <ul style={{ paddingLeft: 20, margin: 0 }}>
            <li>
              <strong style={{ color: C.paper }}>History window:</strong> up to{" "}
              {PARAMETERS.historyWindowDays} calendar days of daily returns (≈{" "}
              {PARAMETERS.tradingDaysPerYear} trading days). Volatility and returns are
              annualized with {PARAMETERS.tradingDaysPerYear} trading days per year.
            </li>
            <li style={{ marginTop: 8 }}>
              <strong style={{ color: C.paper }}>Benchmark:</strong> beta and market-relative
              measures use <strong>{PARAMETERS.benchmark}</strong> (S&amp;P 500) as the market
              proxy.
            </li>
            <li style={{ marginTop: 8 }}>
              <strong style={{ color: C.paper }}>Risk-free rate:</strong>{" "}
              {pct(PARAMETERS.riskFreeRate)} annual — the hurdle in the Sharpe ratio and the
              proxy for the return on cash and the cost of margin borrowing.
            </li>
          </ul>
        </Section>

        <Section title="Two kinds of Value-at-Risk — they are not the same number">
          <p>
            You will see two VaR figures across the product; they answer different
            questions, so never compare them directly:
          </p>
          <ul style={{ paddingLeft: 20, margin: "8px 0 0" }}>
            <li>
              <strong style={{ color: C.paper }}>Historical 1-day VaR (95%)</strong> — used in
              the Health Score&apos;s Downside Protection dimension. It is the empirical
              size of a normal bad <em>day</em>, read straight from your own return history
              (no distribution assumed).
            </li>
            <li style={{ marginTop: 8 }}>
              <strong style={{ color: C.paper }}>21-day Monte Carlo VaR</strong> — shown in
              the full Risk Report. It simulates the portfolio forward over a ~21-trading-day
              (one-month) horizon, so it is a much larger number than the 1-day figure. It is
              a horizon and a method apart; the Health Score does not use it.
            </li>
          </ul>
        </Section>

        <Section title="Leverage, cash and options">
          <ul style={{ paddingLeft: 20, margin: 0 }}>
            <li>
              <strong style={{ color: C.paper }}>Cash</strong> is priced as a constant
              risk-free sleeve, so it reduces volatility (cash drag) without distorting the
              risk-adjusted-return dimension.
            </li>
            <li style={{ marginTop: 8 }}>
              <strong style={{ color: C.paper }}>Margin / leverage</strong> lifts the equity
              return series to the equity-holder level, so volatility, VaR and drawdown scale
              with leverage — while the Sharpe (asset-mix quality) stays leverage-invariant.
            </li>
            <li style={{ marginTop: 8 }}>
              <strong style={{ color: C.paper }}>Options</strong> fold into their underlying as
              a delta-equivalent stock position, then a deterministic, capped penalty reflects
              option-specific risks (short gamma, large negative theta, concentrated expiries,
              uncovered/under-collateralized short calls). The penalty is transparent and
              bounded; it never silently dominates the score.
            </li>
          </ul>
        </Section>

        <Section title="When your data is thin — stabilization, not collapse">
          <p>
            A score is only as trustworthy as its inputs. We compute a deterministic
            data-quality read (price coverage, number of observations, dropped holdings,
            whether beta is estimable). When data is degraded, the dimension scores are
            dampened toward a neutral anchor and the score is labeled lower-confidence —
            rather than letting one missing price produce a confident, catastrophic number.
            A full-data book is unaffected. Every stabilization is surfaced as a reason code
            on the score.
          </p>
        </Section>

        <Section title="What the score is — and is not">
          <ul style={{ paddingLeft: 20, margin: 0 }}>
            <li>
              It is <strong style={{ color: C.paper }}>not a prediction of future returns</strong>{" "}
              and not a recommendation to buy, sell, or hold anything. It describes the risk
              characteristics of the book you hold today.
            </li>
            <li style={{ marginTop: 8 }}>
              It is a <strong style={{ color: C.paper }}>single-currency, US-equity-centric</strong>{" "}
              view built from daily price history; it cannot see private assets, held-away
              accounts, or fundamentals it has no data for.
            </li>
            <li style={{ marginTop: 8 }}>
              Short history, illiquid names, or missing prices make any risk estimate less
              reliable — the confidence label and reason codes tell you when that applies.
            </li>
            <li style={{ marginTop: 8 }}>
              The AI only <em>explains</em> these numbers. It never invents a figure.
            </li>
          </ul>
        </Section>

        <Section title="Versioning and changelog">
          <p>
            Every score is stamped with the methodology version that produced it. We bump the
            version whenever a threshold, weight, or formula changes, and record it below. Two
            snapshots created under different versions are <strong>not directly comparable</strong>
            : the trend view will say the methodology changed rather than present the
            difference as a market or holdings move.
          </p>
          <div style={{ marginTop: 14 }}>
            {SCORE_CHANGELOG.map((e) => (
              <div
                key={e.version}
                style={{
                  borderLeft: `2px solid ${C.teal}`,
                  paddingLeft: 14,
                  marginBottom: 14,
                }}
              >
                <p style={{ margin: 0, color: C.paper, fontFamily: "ui-monospace, monospace" }}>
                  {e.version} · {e.date}
                </p>
                <p style={{ margin: "4px 0 0", fontSize: 15, color: C.slate }}>{e.summary}</p>
              </div>
            ))}
          </div>
        </Section>

        <div style={{ display: "flex", gap: 14, flexWrap: "wrap", margin: "40px 0 22px" }}>
          <CTA href="/score" lg>
            See your Health Score
          </CTA>
          <CTA href="/learn/portfolio-risk-management" variant="ghost" lg>
            Learn the concepts
          </CTA>
        </div>
        <Disclaimer>Educational analytics — not investment advice.</Disclaimer>
      </article>
    </MarketingShell>
  );
}
