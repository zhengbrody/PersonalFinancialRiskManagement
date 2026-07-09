/**
 * /learn — the educational hub. Server component (SSR/SEO) on the premium dark
 * <MarketingShell/>. Lists every topic with its blurb + an ItemList JSON-LD so
 * the hub is crawlable.
 */

import type { Metadata } from "next";
import { LEARN_TOPICS } from "@/lib/learn-content";
import { MarketingShell } from "@/components/marketing/marketing-shell";
import { C } from "@/components/marketing/theme";
import { Band, CTA, Disclaimer, Em, MarketingCard, MarketingHero, SecTitle } from "@/components/marketing/primitives";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://mindmarket.app";

export const metadata: Metadata = {
  title: "Learn portfolio risk — plain-English guides for individual investors",
  description:
    "Free, example-led guides to portfolio risk: VaR & CVaR, factor exposure, stress testing, margin risk, options Greeks, and risk-first stock research.",
  alternates: { canonical: "/learn" },
  openGraph: {
    type: "website",
    title: "Learn portfolio risk — MindMarket",
    description:
      "Free, example-led guides to portfolio risk for individual investors: VaR/CVaR, factor exposure, stress testing, margin, options, and stock research.",
    url: `${SITE_URL}/learn`,
    siteName: "MindMarket",
    images: ["/og.jpg?v=2"],
  },
  twitter: { card: "summary_large_image" },
};

export default function LearnHubPage() {
  const itemListLd = {
    "@context": "https://schema.org",
    "@type": "ItemList",
    name: "MindMarket Learn — portfolio risk guides",
    itemListElement: LEARN_TOPICS.map((t, i) => ({
      "@type": "ListItem",
      position: i + 1,
      url: `${SITE_URL}/learn/${t.slug}`,
      name: t.title,
    })),
  };

  return (
    <MarketingShell>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(itemListLd) }}
      />
      <MarketingHero
        eyebrow="Learn"
        title={
          <>
            Understand the risk you <Em>already own</Em>
          </>
        }
        lede="Plain-English, example-led guides to portfolio risk — the same concepts the Health Score and Risk Report are built on. No jargon, no buy/sell calls."
      />

      <Band>
        <div
          className="mm-hero-grid"
          style={{ display: "grid", gridTemplateColumns: "repeat(2,1fr)", gap: 16 }}
        >
          {LEARN_TOPICS.map((t) => (
            <MarketingCard key={t.slug} href={`/learn/${t.slug}`}>
              <p
                style={{
                  fontSize: 11,
                  fontWeight: 600,
                  textTransform: "uppercase",
                  letterSpacing: ".12em",
                  color: C.teal,
                  margin: 0,
                }}
              >
                {t.eyebrow}
              </p>
              <h2 style={{ fontSize: 18, margin: "6px 0 8px", lineHeight: 1.25, letterSpacing: "-0.01em" }}>
                {t.title}
              </h2>
              <p style={{ fontSize: 14, lineHeight: 1.6, color: C.slate, margin: 0 }}>{t.description}</p>
            </MarketingCard>
          ))}
        </div>
      </Band>

      <Band>
        <div
          style={{
            borderRadius: 20,
            border: `1px solid ${C.hair}`,
            background: C.cardGrad,
            padding: "40px 28px",
            textAlign: "center",
          }}
        >
          <SecTitle>Ready to see it on a portfolio?</SecTitle>
          <p style={{ fontSize: 16, color: C.slate, margin: "12px auto 24px", maxWidth: "34em" }}>
            Run a deterministic sample cockpit, or score your own holdings free.
          </p>
          <div style={{ display: "flex", gap: 12, justifyContent: "center", flexWrap: "wrap" }}>
            <CTA href="/demo-risk-check" variant="ghost">
              Run a sample portfolio
            </CTA>
            <CTA href="/signup">Create free account</CTA>
          </div>
        </div>
        <div style={{ marginTop: 24 }}>
          <Disclaimer>Educational content only — not investment advice.</Disclaimer>
        </div>
      </Band>
    </MarketingShell>
  );
}
