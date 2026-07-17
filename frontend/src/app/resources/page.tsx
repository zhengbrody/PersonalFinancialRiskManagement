/**
 * /resources — crawlable hub for the product workflow, educational guides,
 * methodology, and focused portfolio-risk pages.
 */

import Link from "next/link";
import { MarketingShell } from "@/components/marketing/marketing-shell";
import { C, display, eyebrow } from "@/components/marketing/theme";
import { LEARN_TOPICS } from "@/lib/learn-content";
import { pageMetadata } from "@/lib/site";

export const metadata = pageMetadata({
  title: "Portfolio Risk Resources — Workflow, Guides & Methodology",
  description:
    "Explore the MindMarket product workflow, risk methodology, and plain-English guides to VaR, stress testing, concentration, margin, factors, drawdown, and stock research.",
  path: "/resources",
  ogType: "website",
});

const SOLUTION_PAGES: { href: string; title: string; blurb: string }[] = [
  {
    href: "/portfolio-risk-management",
    title: "Portfolio risk management software",
    blurb: "VaR, CVaR, drawdown, stress testing, and concentration on your whole book.",
  },
  {
    href: "/ai-portfolio-analysis",
    title: "AI portfolio analysis",
    blurb: "Deterministic risk math plus plain-English AI explanations of what’s driving it.",
  },
  {
    href: "/portfolio-var-stress-testing",
    title: "Portfolio VaR & stress testing",
    blurb: "Value-at-Risk, CVaR, and market-shock scenarios for your holdings.",
  },
  {
    href: "/personal-portfolio-risk-analysis",
    title: "Personal portfolio risk analysis",
    blurb: "A risk read built for individual investors, not institutions.",
  },
  {
    href: "/margin-risk-calculator",
    title: "Margin risk calculator",
    blurb: "Net equity, leverage, buying power, stress loss, and distance to a margin call.",
  },
  {
    href: "/portfolio-stress-test",
    title: "Portfolio stress test",
    blurb: "See the damage from a −10%, −20%, or −30% market move before it happens.",
  },
  {
    href: "/stock-portfolio-concentration-risk",
    title: "Concentration risk",
    blurb: "Top-position weights, sector exposure, and component VaR — where your risk hides.",
  },
  {
    href: "/robinhood-margin-risk",
    title: "Robinhood margin risk",
    blurb: "Buying power, cash, leverage, and stress loss for a Robinhood-style account.",
  },
  {
    href: "/sample-risk-report",
    title: "Sample risk report",
    blurb: "A shareable example of a full MindMarket portfolio risk report.",
  },
];

const START_HERE = [
  {
    href: "/product#workflow",
    title: "See the operating workflow",
    blurb: "Understand how Today, Analyze, Test, Plan, and Review fit together.",
  },
  {
    href: "/demo-risk-check",
    title: "Try a sample risk test",
    blurb: "Move a market shock and inspect the holdings driving the estimated loss.",
  },
  {
    href: "/methodology/health-score",
    title: "Audit the Health Score",
    blurb: "Read the exact inputs, weights, safeguards, data-quality rules, and limitations.",
  },
  {
    href: "/risk-today",
    title: "Read today's market risk",
    blurb: "View the public elevated-risk probability with VIX, sentiment, and curve context.",
  },
] as const;

function Card({ href, title, blurb }: { href: string; title: string; blurb: string }) {
  return (
    <Link
      href={href}
      className="mm-card"
      style={{
        display: "block",
        borderRadius: 16,
        border: `1px solid ${C.hair}`,
        background: C.cardGrad,
        padding: 20,
        textDecoration: "none",
        height: "100%",
      }}
    >
      <h3 style={{ color: C.paper, fontSize: 17, fontWeight: 600, margin: "0 0 6px" }}>{title}</h3>
      <p style={{ color: C.slate, fontSize: 14, lineHeight: 1.55, margin: 0 }}>{blurb}</p>
    </Link>
  );
}

export default function ResourcesPage() {
  return (
    <MarketingShell>
      <main
        style={{
          maxWidth: 1080,
          margin: "0 auto",
          padding: "120px 24px 80px",
          display: "flex",
          flexDirection: "column",
          gap: 48,
        }}
      >
        <header style={{ display: "flex", flexDirection: "column", gap: 16, maxWidth: "44em" }}>
          <p style={{ ...eyebrow, margin: 0 }}>Resources</p>
          <h1 style={{ ...display, color: C.paper, fontSize: "clamp(34px,5vw,54px)", fontWeight: 400, margin: 0, lineHeight: 1.05 }}>
            Guides &amp; tools for portfolio risk
          </h1>
          <p style={{ color: C.slate, fontSize: 18, lineHeight: 1.6, margin: 0 }}>
            Start with the decision workflow, inspect the methodology, or learn one metric at a
            time. Every path links the concept back to a practical portfolio question.
          </p>
        </header>

        <section style={{ display: "flex", flexDirection: "column", gap: 18 }}>
          <h2 style={{ ...display, color: C.paper, fontSize: 28, fontWeight: 400, margin: 0 }}>
            Start here
          </h2>
          <div className="mm-resource-grid" style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 16 }}>
            {START_HERE.map((p) => (
              <Card key={p.href} href={p.href} title={p.title} blurb={p.blurb} />
            ))}
          </div>
        </section>

        {/* Guides */}
        <section style={{ display: "flex", flexDirection: "column", gap: 18 }}>
          <h2 style={{ ...display, color: C.paper, fontSize: 28, fontWeight: 400, margin: 0 }}>Guides</h2>
          <div
            className="mm-resource-grid"
            style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16 }}
          >
            {LEARN_TOPICS.map((t) => (
              <Card key={t.slug} href={`/learn/${t.slug}`} title={t.title} blurb={t.description} />
            ))}
          </div>
        </section>

        {/* Tools & solutions */}
        <section style={{ display: "flex", flexDirection: "column", gap: 18 }}>
          <h2 style={{ ...display, color: C.paper, fontSize: 28, fontWeight: 400, margin: 0 }}>
            Tools &amp; solutions
          </h2>
          <div
            className="mm-resource-grid"
            style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16 }}
          >
            {SOLUTION_PAGES.map((p) => (
              <Card key={p.href} href={p.href} title={p.title} blurb={p.blurb} />
            ))}
          </div>
        </section>
      </main>
    </MarketingShell>
  );
}
