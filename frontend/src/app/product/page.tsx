/** /product — public, crawlable product story for the Portfolio Risk OS. */

import { MarketingShell } from "@/components/marketing/marketing-shell";
import { C } from "@/components/marketing/theme";
import {
  Band,
  CTA,
  Disclaimer,
  Em,
  Eyebrow,
  MarketingHero,
  SecTitle,
} from "@/components/marketing/primitives";
import {
  ProductSurfaceGrid,
  ComparisonCapabilities,
  RiskWorkflow,
} from "@/components/marketing/risk-os-story";
import { SampleComparison } from "@/components/marketing/sample-comparison";
import { pageMetadata } from "@/lib/site";

export const metadata = pageMetadata({
  title: "Understand Portfolio Risk & Compare Changes",
  description:
    "See how MindMarket connects daily risk priorities, a unified Analyze workspace, Research-to-Test scenarios, saved risk plans, alerts, and a grounded portfolio Copilot.",
  path: "/product",
  ogType: "website",
});

export default function ProductPage() {
  return (
    <MarketingShell>
      <MarketingHero
        eyebrow="Understand. Compare. Decide."
        title={
          <>
            A clearer view of risk. A more <Em>considered</Em> next move.
          </>
        }
        lede="Understand what drives your portfolio’s risk, compare a hypothetical change, and keep a plan you can review. Your real holdings stay unchanged throughout the test."
      >
        <div style={{ display: "flex", gap: 14, flexWrap: "wrap", marginTop: 30 }}>
          <CTA href="/demo-risk-check" lg>
            Try a sample portfolio
          </CTA>
          <CTA href="/signup?next=%2Fportfolios%2Fnew" variant="ghost" lg>
            Analyze my portfolio
          </CTA>
        </div>
      </MarketingHero>

      <Band>
        <div className="mm-hero-grid" style={{ display: "grid", gridTemplateColumns: ".8fr 1.2fr", gap: 42, alignItems: "center" }}>
          <div>
            <Eyebrow>Designed around the next decision</Eyebrow>
            <SecTitle>The starting point is Today — not a menu of reports.</SecTitle>
            <p style={{ color: C.slate, fontSize: 16, lineHeight: 1.65, margin: "18px 0 0" }}>
              The active portfolio follows you through every surface. Priorities link directly to
              the relevant Analyze stage, research idea, test, alert, or saved plan, so the product
              helps you find the next relevant analysis. Keeping the portfolio unchanged is also a valid decision.
            </p>
          </div>
          <SampleComparison />
        </div>
      </Band>

      <Band id="workflow">
        <Eyebrow>The operating loop</Eyebrow>
        <SecTitle>From signal to saved decision — then back for review.</SecTitle>
        <p style={{ color: C.slate, fontSize: 16, lineHeight: 1.65, margin: "16px 0 36px", maxWidth: "46em" }}>
          Each stage has a distinct job. The workflow is connected, but the underlying risk math,
          evidence, scenario assumptions, and user decisions stay visibly separate.
        </p>
        <RiskWorkflow />
      </Band>

      <Band>
        <Eyebrow>Five connected surfaces</Eyebrow>
        <SecTitle>Deep analysis when you need it. A clear next step when you don&apos;t.</SecTitle>
        <div style={{ marginTop: 36 }}>
          <ProductSurfaceGrid />
        </div>
      </Band>

      <Band>
        <Eyebrow>What each test actually covers</Eyebrow>
        <SecTitle>Choose the right comparison for your question.</SecTitle>
        <div style={{ marginTop: 28 }}><ComparisonCapabilities /></div>
      </Band>

      <Band>
        <Eyebrow>Safety and evidence</Eyebrow>
        <div
          style={{
            borderRadius: 18,
            border: "1px solid rgba(224,174,42,.28)",
            background: "rgba(224,174,42,.06)",
            padding: 28,
          }}
        >
          <SecTitle>
            Tests are hypothetical. The AI <Em>explains</Em> computed evidence.
          </SecTitle>
          <p style={{ fontSize: 16, lineHeight: 1.65, color: C.slate, margin: "16px 0 0", maxWidth: "48em" }}>
            Research-to-Test re-scores an equity-only sandbox; it never places a
            trade or changes saved holdings. Available Health Score, VaR, factor exposure and scenario losses
            come from calculation services, with coverage specific to each analysis. Copilot can explain and navigate that evidence;
            missing or stale critical inputs can lower confidence or prevent a result.
            AI explanations can still be wrong. Options support depends on contract details and
            data availability; Copilot comparison does not edit option legs or optimize every strategy.
          </p>
        </div>
      </Band>

      <Band>
        <SecTitle>Start with a portfolio. Return with a decision to review.</SecTitle>
        <div style={{ display: "flex", gap: 14, flexWrap: "wrap", margin: "28px 0 20px" }}>
          <CTA href="/signup" lg>
            Create my risk workspace
          </CTA>
          <CTA href="/learn" variant="ghost" lg>
            Learn the risk concepts
          </CTA>
        </div>
        <Disclaimer>Educational analytics — not investment advice.</Disclaimer>
      </Band>
    </MarketingShell>
  );
}
