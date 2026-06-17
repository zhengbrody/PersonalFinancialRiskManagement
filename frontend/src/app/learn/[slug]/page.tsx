/**
 * /learn/[slug] — one educational topic. Server component (SSR): Googlebot sees
 * the full text without hydration. Per-topic metadata + FAQPage + BreadcrumbList
 * JSON-LD. Content lives in lib/learn-content.ts; this file is the dark-themed
 * reading shell on <MarketingShell/>.
 */

import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { LEARN_BY_SLUG, LEARN_SLUGS } from "@/lib/learn-content";
import { MarketingShell } from "@/components/marketing/marketing-shell";
import { C, display } from "@/components/marketing/theme";
import { CTA, CTABox, Disclaimer } from "@/components/marketing/primitives";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://mindmarket.app";

export function generateStaticParams() {
  return LEARN_SLUGS.map((slug) => ({ slug }));
}

export function generateMetadata({ params }: { params: { slug: string } }): Metadata {
  const topic = LEARN_BY_SLUG[params.slug];
  if (!topic) return { title: "Learn" };
  const url = `${SITE_URL}/learn/${topic.slug}`;
  return {
    title: topic.metaTitle,
    description: topic.description,
    alternates: { canonical: `/learn/${topic.slug}` },
    openGraph: {
      type: "article",
      title: topic.metaTitle,
      description: topic.description,
      url,
      siteName: "MindMarket",
      images: ["/og.jpg"],
    },
    twitter: { card: "summary_large_image", title: topic.metaTitle, description: topic.description },
  };
}

const linkStyle = { color: C.teal, textDecoration: "none" };

export default function LearnTopicPage({ params }: { params: { slug: string } }) {
  const topic = LEARN_BY_SLUG[params.slug];
  if (!topic) notFound();

  const faqLd = {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: topic.faqs.map((f) => ({
      "@type": "Question",
      name: f.q,
      acceptedAnswer: { "@type": "Answer", text: f.a },
    })),
  };
  const breadcrumbLd = {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: [
      { "@type": "ListItem", position: 1, name: "Home", item: SITE_URL },
      { "@type": "ListItem", position: 2, name: "Learn", item: `${SITE_URL}/learn` },
      { "@type": "ListItem", position: 3, name: topic.title, item: `${SITE_URL}/learn/${topic.slug}` },
    ],
  };

  return (
    <MarketingShell>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(faqLd) }} />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(breadcrumbLd) }}
      />

      <article style={{ maxWidth: 760, margin: "0 auto", padding: "120px 24px 48px" }}>
        <nav style={{ fontSize: 13, color: C.slate, marginBottom: 24 }}>
          <Link href="/" style={linkStyle}>
            Home
          </Link>{" "}
          ›{" "}
          <Link href="/learn" style={linkStyle}>
            Learn
          </Link>{" "}
          › <span style={{ color: C.paper }}>{topic.title}</span>
        </nav>

        <header style={{ marginBottom: 36 }}>
          <p
            style={{
              fontSize: 12,
              fontWeight: 600,
              textTransform: "uppercase",
              letterSpacing: ".18em",
              color: C.teal,
              margin: "0 0 14px",
            }}
          >
            {topic.eyebrow}
          </p>
          <h1
            style={{
              ...display,
              fontWeight: 400,
              fontSize: "clamp(34px,4.6vw,52px)",
              lineHeight: 1.06,
              letterSpacing: "-0.01em",
              margin: "0 0 18px",
              color: C.paper,
            }}
          >
            {topic.title}
          </h1>
          <p style={{ fontSize: 19, lineHeight: 1.6, color: C.slate, margin: 0 }}>{topic.intro}</p>
        </header>

        <div style={{ display: "flex", flexDirection: "column", gap: 36 }}>
          {topic.sections.map((s, i) => (
            <section key={i}>
              <h2
                style={{
                  fontSize: 24,
                  fontWeight: 600,
                  letterSpacing: "-0.01em",
                  margin: "0 0 14px",
                  color: C.paper,
                }}
              >
                {s.heading}
              </h2>
              {s.paragraphs.map((p, j) => (
                <p key={j} style={{ fontSize: 16.5, lineHeight: 1.7, color: C.slate, margin: "0 0 14px" }}>
                  {p}
                </p>
              ))}
              {s.example && (
                <div
                  style={{
                    borderRadius: 12,
                    border: "1px solid rgba(47,167,188,.28)",
                    background: "rgba(47,167,188,.07)",
                    padding: "16px 18px",
                  }}
                >
                  <p
                    style={{
                      fontSize: 11.5,
                      fontWeight: 700,
                      textTransform: "uppercase",
                      letterSpacing: ".12em",
                      color: C.teal,
                      margin: 0,
                    }}
                  >
                    {s.example.label}
                  </p>
                  <p style={{ fontSize: 15, lineHeight: 1.6, color: C.paper, margin: "6px 0 0" }}>
                    {s.example.body}
                  </p>
                </div>
              )}
            </section>
          ))}
        </div>

        {/* CTA */}
        <div style={{ marginTop: 44 }}>
          <CTABox
            headline="See it on a real book"
            lede="Run a sample portfolio, or score your own in seconds."
          >
            <CTA href="/demo-risk-check" variant="ghost">
              Run a sample portfolio
            </CTA>
            <CTA href="/signup">Create free account</CTA>
          </CTABox>
        </div>

        {/* FAQ */}
        <section style={{ marginTop: 44 }}>
          <h2 style={{ fontSize: 24, fontWeight: 600, letterSpacing: "-0.01em", margin: "0 0 16px", color: C.paper }}>
            Frequently asked
          </h2>
          <div style={{ borderRadius: 14, border: `1px solid ${C.hair}`, overflow: "hidden" }}>
            {topic.faqs.map((f, i) => (
              <div
                key={i}
                style={{
                  padding: "18px 20px",
                  borderTop: i === 0 ? "none" : `1px solid ${C.hair}`,
                }}
              >
                <p style={{ fontWeight: 600, margin: 0, color: C.paper }}>{f.q}</p>
                <p style={{ fontSize: 15, lineHeight: 1.6, color: C.slate, margin: "6px 0 0" }}>{f.a}</p>
              </div>
            ))}
          </div>
        </section>

        {/* Related */}
        {topic.related.length > 0 && (
          <section style={{ marginTop: 40 }}>
            <p
              style={{
                fontSize: 12,
                fontWeight: 600,
                textTransform: "uppercase",
                letterSpacing: ".14em",
                color: C.slate,
                margin: "0 0 12px",
              }}
            >
              Keep learning
            </p>
            <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 8 }}>
              {topic.related.map((slug) => {
                const r = LEARN_BY_SLUG[slug];
                if (!r) return null;
                return (
                  <li key={slug}>
                    <Link href={`/learn/${slug}`} style={{ ...linkStyle, fontSize: 15 }}>
                      {r.title} →
                    </Link>
                  </li>
                );
              })}
            </ul>
          </section>
        )}

        <div style={{ marginTop: 40, borderTop: `1px solid ${C.hair}`, paddingTop: 20 }}>
          <Disclaimer>
            Educational content only — not investment advice, and not a recommendation to buy or sell
            any security. MindMarket helps you measure and understand risk you already own.
          </Disclaimer>
        </div>
      </article>
    </MarketingShell>
  );
}
