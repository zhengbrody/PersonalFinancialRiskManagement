/**
 * /learn — the educational hub. Server component (SSR/SEO) on the premium dark
 * <MarketingShell/>. Lists every topic with its blurb + an ItemList JSON-LD so
 * the hub is crawlable.
 */

import { LEARN_TOPICS } from "@/lib/learn-content";
import { MarketingShell } from "@/components/marketing/marketing-shell";
import { C } from "@/components/marketing/theme";
import { Band, CTA, Disclaimer, Em, MarketingCard, MarketingHero, SecTitle } from "@/components/marketing/primitives";
import { SITE_URL, pageMetadata } from "@/lib/site";

export const metadata = pageMetadata({
  title: "Learn Portfolio Risk — Plain-English Investor Guides",
  description:
    "Example-led guides to VaR, CVaR, factor exposure, stress testing, margin risk, options Greeks, drawdown, diversification, and risk-first stock research.",
  path: "/learn",
  ogType: "website",
});

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
        lede="Plain-English, example-led guides to the concepts used inside Analyze, stress tests, and risk plans. Learn the metric, then see where it changes a portfolio decision."
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
            Run a deterministic sample cockpit, or bring the concepts into a connected portfolio workflow.
          </p>
          <div style={{ display: "flex", gap: 12, justifyContent: "center", flexWrap: "wrap" }}>
            <CTA href="/demo-risk-check" variant="ghost">
              Run a sample portfolio
            </CTA>
            <CTA href="/signup">Create risk workspace</CTA>
          </div>
        </div>
        <div style={{ marginTop: 24 }}>
          <Disclaimer>Educational content only — not investment advice.</Disclaimer>
        </div>
      </Band>
    </MarketingShell>
  );
}
