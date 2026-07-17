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
  RiskOsPreview,
  RiskWorkflow,
} from "@/components/marketing/risk-os-story";
import { pageMetadata } from "@/lib/site";

export const metadata = pageMetadata({
  title: "Portfolio Risk OS — Today, Analyze, Test, Plan & Review",
  description:
    "See how MindMarket connects daily risk priorities, a unified Analyze workspace, Research-to-Test scenarios, saved risk plans, alerts, and a grounded portfolio Copilot.",
  path: "/product",
  ogType: "website",
});

export default function ProductPage() {
  return (
    <MarketingShell>
      <MarketingHero
        eyebrow="Portfolio Risk OS"
        title={
          <>
            One place to see, test, and <Em>remember</Em> portfolio risk decisions
          </>
        }
        lede="MindMarket replaces scattered scorecards and forgotten reports with a connected workflow. Today prioritizes what changed; Analyze explains why; Research-to-Test models a response; plans and alerts bring the decision back when it needs review."
      >
        <div style={{ display: "flex", gap: 14, flexWrap: "wrap", marginTop: 30 }}>
          <CTA href="/demo-risk-check" lg>
            Explore the interactive demo
          </CTA>
          <CTA href="/signup" variant="ghost" lg>
            Create my risk workspace
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
              always gives you a clear next action.
            </p>
          </div>
          <RiskOsPreview />
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
            Research-to-Test and scenario tools re-score a sandbox portfolio; they never place a
            trade or change saved holdings. Health Score, VaR, factor exposure, and scenario losses
            are computed by deterministic services. Copilot can explain and navigate that evidence,
            but missing or stale critical data lowers confidence instead of being filled with a guess.
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
