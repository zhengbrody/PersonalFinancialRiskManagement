/**
 * /demo-risk-check — public, no-auth Demo Risk Check on the premium dark
 * <MarketingShell/>. The fastest path to "I get it": a real, deterministic risk
 * cockpit on a sample book with a one-click high-growth stress toggle. Server
 * component (SSR/SEO) wrapping the client <SampleCockpit/> (which uses theme
 * tokens → renders dark under the shell's `dark` root); a tiny client ping fires
 * `demo_started` on mount.
 */

import type { Metadata } from "next";
import { SampleCockpit } from "@/components/sample-cockpit";
import { DemoStartedPing } from "@/components/demo-started-ping";
import { MarketingShell } from "@/components/marketing/marketing-shell";
import { C } from "@/components/marketing/theme";
import { CTA, CTABox, Disclaimer, Em, MarketingHero } from "@/components/marketing/primitives";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://mindmarket.app";

export const metadata: Metadata = {
  title: "Demo Risk Check — see your portfolio's hidden risk in 30 seconds",
  description:
    "Try MindMarket's risk cockpit free, no sign-in: score a balanced book, then one-click stress a high-growth portfolio to see concentration, volatility, and crash exposure. Every number is computed, nothing is invented.",
  alternates: { canonical: "/demo-risk-check" },
  openGraph: {
    type: "website",
    title: "MindMarket — Demo Risk Check",
    description:
      "Score a sample portfolio and stress a high-growth book in 30 seconds — no sign-in. Deterministic risk math, not AI guesswork.",
    url: `${SITE_URL}/demo-risk-check`,
    siteName: "MindMarket",
    images: ["/og.jpg?v=2"],
  },
  twitter: { card: "summary_large_image" },
};

export default function DemoRiskCheckPage() {
  return (
    <MarketingShell>
      <DemoStartedPing />
      <MarketingHero
        eyebrow="Demo Risk Check"
        title={
          <>
            See what can break a portfolio — <Em>before</Em> you add more risk
          </>
        }
        lede={
          <>
            No sign-in. Start with a balanced book, then one-click{" "}
            <span style={{ color: C.paper, fontWeight: 500 }}>stress a high-growth portfolio</span> to
            see how concentration, volatility, and a tech-and-crypto selloff change the picture.
          </>
        }
      />

      <div style={{ maxWidth: 920, margin: "0 auto", padding: "28px 24px 8px" }}>
        <SampleCockpit />
      </div>

      <div style={{ maxWidth: 920, margin: "0 auto", padding: "16px 24px 64px" }}>
        <CTABox
          headline="Want this for your own portfolio?"
          lede="Add your holdings (or import a CSV) and get a real Health Score, risk report, and AI copilot — free during beta."
        >
          <CTA href="/signup">Analyze my portfolio</CTA>
          <CTA href="/research" variant="ghost">
            Research a stock
          </CTA>
        </CTABox>
        <div style={{ marginTop: 18 }}>
          <Disclaimer>
            Sample data for illustration — not live prices and not investment advice. Your own
            cockpit uses real market data with full source provenance.
          </Disclaimer>
        </div>
      </div>
    </MarketingShell>
  );
}
