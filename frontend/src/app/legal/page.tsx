/**
 * /legal — index of the legal documents (Terms / Privacy / Disclaimer).
 * Server component on <MarketingShell/>; links to each /legal/[doc].
 */

import type { Metadata } from "next";
import Link from "next/link";
import { LEGAL_DOCS } from "@/lib/legal-content";
import { MarketingShell } from "@/components/marketing/marketing-shell";
import { C, display } from "@/components/marketing/theme";

export const metadata: Metadata = {
  title: "Legal — MindMarket",
  description: "Terms of Service, Privacy Policy, and Financial Disclaimer for MindMarket AI.",
  alternates: { canonical: "/legal" },
};

export default function LegalIndexPage() {
  return (
    <MarketingShell>
      <article style={{ maxWidth: 760, margin: "0 auto", padding: "120px 24px 56px" }}>
        <h1
          style={{
            ...display,
            fontWeight: 400,
            fontSize: "clamp(34px,4.6vw,52px)",
            lineHeight: 1.06,
            letterSpacing: "-0.01em",
            margin: "0 0 14px",
            color: C.paper,
          }}
        >
          Legal
        </h1>
        <p style={{ fontSize: 18, lineHeight: 1.6, color: C.slate, margin: "0 0 32px" }}>
          The terms, privacy practices, and financial disclaimer that govern MindMarket AI during the
          beta. MindMarket is an educational product — nothing here is investment advice.
        </p>

        <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 14 }}>
          {LEGAL_DOCS.map((d) => (
            <li key={d.slug}>
              <Link
                href={`/legal/${d.slug}`}
                style={{
                  display: "block",
                  textDecoration: "none",
                  borderRadius: 14,
                  border: `1px solid ${C.hair}`,
                  padding: "18px 20px",
                }}
              >
                <span style={{ fontSize: 18, fontWeight: 600, color: C.paper }}>{d.title} →</span>
                <span style={{ display: "block", fontSize: 15, lineHeight: 1.6, color: C.slate, marginTop: 6 }}>
                  {d.description}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </article>
    </MarketingShell>
  );
}
