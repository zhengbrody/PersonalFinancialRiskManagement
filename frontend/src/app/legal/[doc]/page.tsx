/**
 * /legal/[doc] — Terms of Service / Privacy Policy / Financial Disclaimer.
 * Server component (SSR): the full text is in the HTML for crawlers + reachable
 * without auth (required before charging real money). Content lives in
 * lib/legal-content.ts; this is the dark reading shell on <MarketingShell/>.
 */

import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { LEGAL_BY_SLUG, LEGAL_DOCS, LEGAL_SLUGS } from "@/lib/legal-content";
import { MarketingShell } from "@/components/marketing/marketing-shell";
import { C, display } from "@/components/marketing/theme";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://mindmarket.app";

export function generateStaticParams() {
  return LEGAL_SLUGS.map((doc) => ({ doc }));
}

export function generateMetadata({ params }: { params: { doc: string } }): Metadata {
  const d = LEGAL_BY_SLUG[params.doc];
  if (!d) return { title: "Legal" };
  const url = `${SITE_URL}/legal/${d.slug}`;
  return {
    title: d.metaTitle,
    description: d.description,
    alternates: { canonical: `/legal/${d.slug}` },
    openGraph: {
      type: "article",
      title: d.metaTitle,
      description: d.description,
      url,
      siteName: "mindmarket.app",
      images: ["/og.jpg?v=3"],
    },
    twitter: { card: "summary_large_image", title: d.metaTitle, description: d.description },
  };
}

const linkStyle = { color: C.teal, textDecoration: "none" };

export default function LegalDocPage({ params }: { params: { doc: string } }) {
  const d = LEGAL_BY_SLUG[params.doc];
  if (!d) notFound();

  const breadcrumbLd = {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: [
      { "@type": "ListItem", position: 1, name: "Home", item: SITE_URL },
      { "@type": "ListItem", position: 2, name: "Legal", item: `${SITE_URL}/legal` },
      { "@type": "ListItem", position: 3, name: d.title, item: `${SITE_URL}/legal/${d.slug}` },
    ],
  };

  return (
    <MarketingShell>
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
          <Link href="/legal" style={linkStyle}>
            Legal
          </Link>{" "}
          › <span style={{ color: C.paper }}>{d.title}</span>
        </nav>

        <header style={{ marginBottom: 36 }}>
          <h1
            style={{
              ...display,
              fontWeight: 400,
              fontSize: "clamp(34px,4.6vw,52px)",
              lineHeight: 1.06,
              letterSpacing: "-0.01em",
              margin: "0 0 12px",
              color: C.paper,
            }}
          >
            {d.title}
          </h1>
          <p style={{ fontSize: 13, color: C.slate, margin: "0 0 18px" }}>
            Last updated: {d.lastUpdated}
          </p>
          <p style={{ fontSize: 18, lineHeight: 1.6, color: C.slate, margin: 0 }}>{d.intro}</p>
        </header>

        <div style={{ display: "flex", flexDirection: "column", gap: 30 }}>
          {d.sections.map((s, i) => (
            <section key={i}>
              <h2
                style={{
                  fontSize: 22,
                  fontWeight: 600,
                  letterSpacing: "-0.01em",
                  margin: "0 0 12px",
                  color: C.paper,
                }}
              >
                {s.heading}
              </h2>
              {s.blocks.map((b, j) => {
                if (b.kind === "list") {
                  return (
                    <ul
                      key={j}
                      style={{
                        margin: "0 0 12px",
                        paddingLeft: 22,
                        color: C.slate,
                        fontSize: 16,
                        lineHeight: 1.7,
                      }}
                    >
                      {b.items.map((it, k) => (
                        <li key={k} style={{ marginBottom: 4 }}>
                          {it}
                        </li>
                      ))}
                    </ul>
                  );
                }
                if (b.kind === "lead") {
                  return (
                    <p key={j} style={{ fontSize: 16, lineHeight: 1.7, color: C.slate, margin: "0 0 8px" }}>
                      <strong style={{ color: C.paper }}>{b.label}</strong>
                      {b.text ?? ""}
                    </p>
                  );
                }
                return (
                  <p key={j} style={{ fontSize: 16, lineHeight: 1.7, color: C.slate, margin: "0 0 12px" }}>
                    {b.text}
                  </p>
                );
              })}
            </section>
          ))}
        </div>

        <div style={{ marginTop: 36, borderTop: `1px solid ${C.hair}`, paddingTop: 22 }}>
          <p style={{ fontSize: 14, color: C.slate, margin: "0 0 14px" }}>
            Questions?{" "}
            <a href={`mailto:${d.contactEmail}`} style={linkStyle}>
              {d.contactEmail}
            </a>
          </p>
          <nav style={{ display: "flex", flexWrap: "wrap", gap: 16, fontSize: 14 }}>
            {LEGAL_DOCS.filter((o) => o.slug !== d.slug).map((o) => (
              <Link key={o.slug} href={`/legal/${o.slug}`} style={linkStyle}>
                {o.title} →
              </Link>
            ))}
          </nav>
        </div>
      </article>
    </MarketingShell>
  );
}
