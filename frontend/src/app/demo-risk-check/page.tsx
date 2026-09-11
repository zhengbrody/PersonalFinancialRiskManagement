/**
 * Public demo: shared local comparison first, separate sample cockpit as an
 * optional drill-down. The existing anonymous API experiment remains gated.
 */

import { SampleCockpit } from "@/components/sample-cockpit";
import { SampleComparison } from "@/components/marketing/sample-comparison";
import { PublicRiskCheck } from "@/components/public-risk-check";
import { isPublicRiskCheckEnabled } from "@/lib/public-risk";
import { DemoStartedPing } from "@/components/demo-started-ping";
import { MarketingShell } from "@/components/marketing/marketing-shell";
import { C } from "@/components/marketing/theme";
import { CTA, CTABox, Disclaimer, Em, MarketingHero } from "@/components/marketing/primitives";
import { pageMetadata } from "@/lib/site";

export const metadata = pageMetadata({
  title: "Interactive Portfolio Demo — Compare a Hypothetical Change",
  description:
    "Try a fictional portfolio without signing in. Reduce a sample position, compare cash versus margin repayment, and inspect the assumptions behind a simplified stress scenario.",
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
            Try a change. <Em>Understand</Em> the difference.
          </>
        }
        lede={
          <>
            No sign-in. Reduce a position in a fictional portfolio, choose what happens to
            the proceeds, and compare the outcome under a hypothetical market fall.
            This is a simplified educational model, not live analysis.
          </>
        }
      />

      <div style={{ maxWidth: 650, margin: "0 auto", padding: "28px 24px 32px" }}>
        <SampleComparison />
      </div>
      <div style={{ maxWidth: 920, margin: "0 auto", padding: "8px 24px 32px" }}>
        <details style={{ border: `1px solid ${C.hair}`, borderRadius: 16, padding: 20 }}>
          <summary style={{ cursor: "pointer", color: C.teal }}>Explore the separate sample risk cockpit</summary>
          <p style={{ color: C.slate, lineHeight: 1.6 }}>A different sample dataset illustrates score and risk drivers. Its numbers are not directly comparable with the change demo above.</p>
          <SampleCockpit />
        </details>
      </div>

      {isPublicRiskCheckEnabled() && (
        <div style={{ maxWidth: 920, margin: "0 auto", padding: "8px 24px 16px" }}>
          <PublicRiskCheck />
        </div>
      )}

      <div style={{ maxWidth: 920, margin: "0 auto", padding: "16px 24px 64px" }}>
        <CTABox
          headline="Move from the sample to your own portfolio."
          lede="Add your holdings, inspect available risk metrics in Analyze, and choose a supported what-if test. Eligible scenarios can be saved for you to revisit; this does not start automatic monitoring."
        >
          <CTA href="/signup?next=%2Fportfolios%2Fnew">Create my risk workspace</CTA>
          <CTA href="/product#workflow" variant="ghost">
            See the full workflow
          </CTA>
        </CTABox>
        <div style={{ marginTop: 18 }}>
          <Disclaimer>
            Sample data for illustration — not live prices and not investment advice. Your own
            analysis depends on available market data; inspect its sources, timestamps and coverage limits.
          </Disclaimer>
        </div>
      </div>
    </MarketingShell>
  );
}
