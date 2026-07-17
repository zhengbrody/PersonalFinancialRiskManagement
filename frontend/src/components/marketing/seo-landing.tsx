/**
 * One template for all migrated SEO landing pages (see lib/seo-content.ts).
 * Server component — the prose is in the initial HTML (no client hydration
 * needed to read it). Reuses MarketingShell + the shared design tokens/
 * primitives, so there is no per-page inline CSS to keep in sync.
 */

import type { Metadata } from "next";
import Link from "next/link";
import { MarketingShell } from "@/components/marketing/marketing-shell";
import { C, display } from "@/components/marketing/theme";
import { CTA, Disclaimer } from "@/components/marketing/primitives";
import { RiskWorkflow } from "@/components/marketing/risk-os-story";
import { SEO_BY_PATH, type SeoPage, type SeoSection } from "@/lib/seo-content";
import { SITE_URL, pageMetadata } from "@/lib/site";

/** Build Next metadata for a migrated SEO page from its content entry. */
export function seoMetadata(path: string): Metadata {
  const p = SEO_BY_PATH[path];
  if (!p) return {};
  return pageMetadata({ title: p.title, description: p.description, path: p.path });
}

function boldLabel(item: string) {
  // "Label: description" → bold the label.
  const i = item.indexOf(":");
  if (i === -1) return item;
  return (
    <>
      <strong style={{ color: C.paper }}>{item.slice(0, i)}</strong>
      {item.slice(i)}
    </>
  );
}

const secTitle: React.CSSProperties = {
  ...display,
  fontSize: 24,
  letterSpacing: "-0.01em",
  margin: "0 0 12px",
  color: C.paper,
};
const cardStyle: React.CSSProperties = {
  borderRadius: 14,
  border: `1px solid ${C.hair}`,
  background: C.surfaceFaint,
  padding: "18px 20px",
};

function Section({ s }: { s: SeoSection }) {
  switch (s.kind) {
    case "prose":
      return (
        <section style={{ marginTop: 36 }}>
          {s.h2 && <h2 style={secTitle}>{s.h2}</h2>}
          {s.body.map((para, i) => (
            <p key={i} style={{ fontSize: 16, lineHeight: 1.7, color: C.slate, margin: "0 0 10px" }}>
              {para}
            </p>
          ))}
        </section>
      );
    case "bullets":
      return (
        <section style={{ marginTop: 36 }}>
          {s.h2 && <h2 style={secTitle}>{s.h2}</h2>}
          <ul style={{ paddingLeft: 20, margin: 0 }}>
            {s.items.map((it) => (
              <li
                key={it}
                style={{ fontSize: 16, lineHeight: 1.7, color: C.slate, marginTop: 6 }}
              >
                {boldLabel(it)}
              </li>
            ))}
          </ul>
        </section>
      );
    case "cards":
      return (
        <section style={{ marginTop: 36 }}>
          {s.h2 && <h2 style={secTitle}>{s.h2}</h2>}
          <div
            className="mm-seo-grid"
            style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 16 }}
          >
            {s.cards.map((c) => (
              <div key={c.title} style={cardStyle}>
                <h3 style={{ fontSize: 16, margin: "0 0 6px", color: C.paper }}>{c.title}</h3>
                <p style={{ fontSize: 14.5, lineHeight: 1.6, color: C.slate, margin: 0 }}>
                  {c.body}
                </p>
              </div>
            ))}
          </div>
        </section>
      );
    case "metrics":
      return (
        <section style={{ marginTop: 36 }}>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
            {s.items.map((m) => (
              <div key={m.label} style={{ ...cardStyle, flex: "1 1 130px", padding: "14px 16px" }}>
                <div
                  style={{
                    fontSize: 11,
                    textTransform: "uppercase",
                    letterSpacing: ".1em",
                    color: C.slateDim,
                  }}
                >
                  {m.label}
                </div>
                <div style={{ ...display, fontSize: 24, color: C.paper, marginTop: 2 }}>
                  {m.value}
                </div>
              </div>
            ))}
          </div>
        </section>
      );
    case "table":
      return (
        <section style={{ marginTop: 36 }}>
          {s.h2 && <h2 style={secTitle}>{s.h2}</h2>}
          <div style={{ overflowX: "auto" }}>
            <table style={{ borderCollapse: "collapse", width: "100%", minWidth: 420 }}>
              <thead>
                <tr>
                  {s.headers.map((h) => (
                    <th
                      key={h}
                      style={{
                        padding: "10px 12px",
                        borderBottom: `1px solid ${C.hairStrong}`,
                        textAlign: "left",
                        color: C.paper,
                        fontSize: 12,
                        textTransform: "uppercase",
                        letterSpacing: ".08em",
                      }}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {s.rows.map((r) => (
                  <tr key={r[0]}>
                    <td
                      style={{
                        padding: "10px 12px",
                        borderBottom: `1px solid ${C.hair}`,
                        color: C.paper,
                        fontWeight: 600,
                        verticalAlign: "top",
                      }}
                    >
                      {r[0]}
                    </td>
                    <td
                      style={{
                        padding: "10px 12px",
                        borderBottom: `1px solid ${C.hair}`,
                        color: C.slate,
                        verticalAlign: "top",
                      }}
                    >
                      {r[1]}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      );
    case "related":
      return (
        <section style={{ marginTop: 36 }}>
          <h2 style={secTitle}>{s.h2}</h2>
          <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 8 }}>
            {s.links.map((l) => (
              <li key={l.href}>
                <Link href={l.href} style={{ color: C.teal, fontSize: 16, textDecoration: "none" }}>
                  {l.label} →
                </Link>
              </li>
            ))}
          </ul>
        </section>
      );
  }
}

export function SeoLanding({ page }: { page: SeoPage }) {
  const structuredData = {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "WebPage",
        "@id": `${SITE_URL}${page.path}#webpage`,
        url: `${SITE_URL}${page.path}`,
        name: page.title,
        description: page.description,
        isPartOf: { "@id": `${SITE_URL}/#website` },
      },
      {
        "@type": "BreadcrumbList",
        itemListElement: [
          { "@type": "ListItem", position: 1, name: "Home", item: SITE_URL },
          { "@type": "ListItem", position: 2, name: "Resources", item: `${SITE_URL}/resources` },
          { "@type": "ListItem", position: 3, name: page.h1, item: `${SITE_URL}${page.path}` },
        ],
      },
    ],
  };
  return (
    <MarketingShell>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(structuredData) }}
      />
      <article style={{ maxWidth: 820, margin: "0 auto", padding: "120px 24px 56px" }}>
        <nav aria-label="Breadcrumb" style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 22, fontSize: 12.5, color: C.slateDim }}>
          <Link href="/" style={{ color: C.slate, textDecoration: "none" }}>Home</Link>
          <span aria-hidden="true">/</span>
          <Link href="/resources" style={{ color: C.slate, textDecoration: "none" }}>Resources</Link>
          <span aria-hidden="true">/</span>
          <span aria-current="page">{page.eyebrow}</span>
        </nav>
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
          {page.eyebrow}
        </p>
        <h1 style={{ ...display, fontSize: 40, lineHeight: 1.1, margin: "8px 0 14px", color: C.paper }}>
          {page.h1}
        </h1>
        {page.lead.map((para, i) => (
          <p key={i} style={{ fontSize: 18, lineHeight: 1.65, color: C.slate, margin: "0 0 12px", maxWidth: "44em" }}>
            {para}
          </p>
        ))}

        {page.crossLink && (
          <div
            style={{
              marginTop: 8,
              borderRadius: 12,
              border: `1px solid ${C.hair}`,
              background: C.surfaceFaint,
              padding: "12px 16px",
            }}
          >
            <Link href={page.crossLink.href} style={{ color: C.teal, fontSize: 15, textDecoration: "none" }}>
              {page.crossLink.label}
            </Link>
          </div>
        )}

        <section style={{ marginTop: 38 }}>
          <h2 style={secTitle}>From this question to a decision you can review</h2>
          <p style={{ fontSize: 15.5, lineHeight: 1.65, color: C.slate, margin: "0 0 18px" }}>
            MindMarket keeps this analysis inside one portfolio workflow: prioritize the issue in
            Today, inspect it in Analyze, test a hypothetical change, save the plan, and return when
            the evidence or market context changes.
          </p>
          <RiskWorkflow compact />
        </section>

        {page.sections.map((s, i) => (
          <Section key={i} s={s} />
        ))}

        <div style={{ display: "flex", gap: 14, flexWrap: "wrap", margin: "40px 0 22px" }}>
          <CTA href={page.cta.href} lg>
            {page.cta.label}
          </CTA>
          <CTA href="/product#workflow" variant="ghost" lg>
            See the full workflow
          </CTA>
        </div>
        <Disclaimer>{page.disclaimer}</Disclaimer>
      </article>
    </MarketingShell>
  );
}
