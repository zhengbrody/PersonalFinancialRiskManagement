/**
 * /product — explains the four pillars (Health Score, Risk Report, Stock
 * Research, Copilot). Server component (SSR/SEO) wearing the premium dark
 * <MarketingShell/>. The SoftwareApplication JSON-LD lives once in the root
 * layout — not duplicated here.
 */

import type { Metadata } from "next";
import { MarketingShell } from "@/components/marketing/marketing-shell";
import { C } from "@/components/marketing/theme";
import {
  Band,
  CTA,
  Disclaimer,
  Em,
  Eyebrow,
  IconChip,
  MarketingCard,
  MarketingHero,
  SecTitle,
} from "@/components/marketing/primitives";
import type { IconName } from "@/components/ui/icon";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://mindmarket.app";

export const metadata: Metadata = {
  title: "Product — Health Score, Risk Report, Stock Research & Copilot",
  description:
    "MindMarket turns your holdings into a 0–1000 Health Score, an institutional-grade Risk Report, source-backed Stock Research, and an AI Copilot grounded in deterministic risk math.",
  alternates: { canonical: "/product" },
  openGraph: {
    type: "website",
    title: "MindMarket — AI portfolio risk analytics",
    description:
      "Health Score, Risk Report, Stock Research, and an AI Copilot grounded in deterministic risk math — for individual investors.",
    url: `${SITE_URL}/product`,
    siteName: "MindMarket",
    images: ["/og.jpg"],
  },
  twitter: { card: "summary_large_image" },
};

const PILLARS: { icon: IconName; name: string; tag: string; body: string; href: string }[] = [
  {
    icon: "score-gauge",
    name: "Portfolio Health Score",
    tag: "0–1000, explained",
    body: "A single 0–1000 score across three dimensions — risk match, risk-adjusted return, and downside protection — with a gauge, the top drivers, and a plain-English explanation of why it moved since your last visit.",
    href: "/learn/portfolio-risk-management",
  },
  {
    icon: "shield",
    name: "Risk Report",
    tag: "Institutional, readable",
    body: "VaR/CVaR, factor exposures, component VaR, a stress-scenario explorer (−10/−20/−30%), per-holding stress losses, concentration, liquidity, and an options/margin cockpit — every figure with its source and freshness.",
    href: "/learn/var-cvar-explained",
  },
  {
    icon: "research",
    name: "Stock Research",
    tag: "Source-backed",
    body: "A compact dossier: valuation vs peers, growth and profitability quality, the analyst view, and news — each field tagged with its provider and a data-confidence badge. The AI verdict lays out the bull and bear case and what would change the view, never a buy/sell call.",
    href: "/learn/stock-research",
  },
  {
    icon: "copilot",
    name: "AI Copilot",
    tag: "Grounded, never invented",
    body: "Ask about your portfolio in plain English. The Copilot answers from vetted, deterministic numbers — it cites its sources and admits when data is missing, instead of inventing confidence.",
    href: "/learn",
  },
];

export default function ProductPage() {
  return (
    <MarketingShell>
      <MarketingHero
        eyebrow="Product"
        title={
          <>
            Understand the risk you already own <Em>before</Em> adding more
          </>
        }
        lede="MindMarket turns your holdings into a clear, source-backed risk cockpit — the same kind of analytics institutions use, made readable for individual investors. Every number is computed from real data; the AI only explains it, never invents it."
      >
        <div style={{ display: "flex", gap: 14, flexWrap: "wrap", marginTop: 30 }}>
          <CTA href="/signup" lg>
            Create free account
          </CTA>
          <CTA href="/demo-risk-check" variant="ghost" lg>
            See a live demo
          </CTA>
        </div>
      </MarketingHero>

      <Band>
        <div
          className="mm-hero-grid"
          style={{ display: "grid", gridTemplateColumns: "repeat(2,1fr)", gap: 20 }}
        >
          {PILLARS.map((p) => (
            <MarketingCard key={p.name} href={p.href}>
              <IconChip name={p.icon} />
              <p
                style={{
                  marginTop: 16,
                  fontSize: 11,
                  fontWeight: 600,
                  textTransform: "uppercase",
                  letterSpacing: ".12em",
                  color: C.teal,
                }}
              >
                {p.tag}
              </p>
              <h2 style={{ fontSize: 20, margin: "6px 0 8px", letterSpacing: "-0.01em" }}>{p.name}</h2>
              <p style={{ fontSize: 14.5, lineHeight: 1.6, color: C.slate, margin: 0 }}>{p.body}</p>
            </MarketingCard>
          ))}
        </div>
      </Band>

      <Band>
        <Eyebrow>The rule we don&apos;t break</Eyebrow>
        <div
          style={{
            borderRadius: 18,
            border: "1px solid rgba(224,174,42,.28)",
            background: "rgba(224,174,42,.06)",
            padding: 28,
          }}
        >
          <SecTitle>
            The AI <Em>explains</Em> the numbers. It never invents them.
          </SecTitle>
          <p style={{ fontSize: 16, lineHeight: 1.65, color: C.slate, margin: "16px 0 0", maxWidth: "46em" }}>
            Scores, VaR, betas, scenario losses, and valuations are computed deterministically in
            Python from market data. The AI is only allowed to explain, rank, and summarize those
            numbers — it can never invent a figure or a price target. Where a data source is missing
            or stale, the product says so instead of guessing.
          </p>
        </div>
      </Band>

      <Band>
        <SecTitle>Ready when you are.</SecTitle>
        <div style={{ display: "flex", gap: 14, flexWrap: "wrap", margin: "28px 0 20px" }}>
          <CTA href="/signup" lg>
            Create free account
          </CTA>
          <CTA href="/learn" variant="ghost" lg>
            Learn the concepts
          </CTA>
        </div>
        <Disclaimer>Educational analytics — not investment advice.</Disclaimer>
      </Band>
    </MarketingShell>
  );
}
