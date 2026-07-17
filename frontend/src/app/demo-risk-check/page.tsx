/**
 * /demo-risk-check — public, no-auth Demo Risk Check on the premium dark
 * <MarketingShell/>. The fastest path to "I get it": a real, deterministic risk
 * cockpit on a sample book with a one-click high-growth stress toggle. Server
 * component (SSR/SEO) wrapping the client <SampleCockpit/> (which uses theme
 * tokens → renders dark under the shell's `dark` root); a tiny client ping fires
 * `demo_started` on mount.
 */

import { SampleCockpit } from "@/components/sample-cockpit";
import { PublicRiskCheck } from "@/components/public-risk-check";
import { isPublicRiskCheckEnabled } from "@/lib/public-risk";
import { DemoStartedPing } from "@/components/demo-started-ping";
import { MarketingShell } from "@/components/marketing/marketing-shell";
import { C } from "@/components/marketing/theme";
import { CTA, CTABox, Disclaimer, Em, MarketingHero } from "@/components/marketing/primitives";
import { pageMetadata } from "@/lib/site";

export const metadata = pageMetadata({
  title: "Interactive Portfolio Risk Demo — Stress a Sample Book",
  description:
    "Explore a sample portfolio risk workflow without signing in: inspect the Health Score, concentration, volatility, and estimated stress losses. Every number is computed and clearly labeled.",
  path: "/demo-risk-check",
  ogType: "website",
});

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

      {isPublicRiskCheckEnabled() && (
        <div style={{ maxWidth: 920, margin: "0 auto", padding: "8px 24px 16px" }}>
          <PublicRiskCheck />
        </div>
      )}

      <div style={{ maxWidth: 920, margin: "0 auto", padding: "16px 24px 64px" }}>
        <CTABox
          headline="Turn a one-time check into an ongoing risk workflow."
          lede="Add your holdings, open Today, trace the risk in Analyze, test a change, and save the decision for review."
        >
          <CTA href="/signup">Create my risk workspace</CTA>
          <CTA href="/product#workflow" variant="ghost">
            See the full workflow
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
