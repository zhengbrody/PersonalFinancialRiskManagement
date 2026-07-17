/**
 * /about — rewritten from the old keyword-stuffed static page into a genuine
 * about/trust page: why the product exists, how it works (methodology), its
 * limitations, data provenance, privacy & security, and operator contact.
 * Server component; MarketingShell + shared tokens (no per-page inline CSS
 * system). Organization JSON-LD for entity SEO.
 */

import Link from "next/link";
import { MarketingShell } from "@/components/marketing/marketing-shell";
import { C, display } from "@/components/marketing/theme";
import { CTA, Disclaimer } from "@/components/marketing/primitives";
import { pageMetadata } from "@/lib/site";

export const metadata = pageMetadata({
  title: "About MindMarket — A Portfolio Risk OS for Investors",
  description:
    "Why MindMarket turns portfolio analytics into a repeatable Today, Analyze, Test, Plan, and Review workflow — plus methodology, limits, data provenance, and privacy.",
  path: "/about",
  ogType: "website",
});

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section style={{ marginTop: 40 }}>
      <h2 style={{ ...display, fontSize: 24, letterSpacing: "-0.01em", margin: "0 0 12px", color: C.paper }}>
        {title}
      </h2>
      <div style={{ fontSize: 16, lineHeight: 1.7, color: C.slate }}>{children}</div>
    </section>
  );
}

export default function AboutPage() {
  return (
    <MarketingShell>
      <article style={{ maxWidth: 820, margin: "0 auto", padding: "120px 24px 56px" }}>
        <p style={{ fontSize: 12, fontWeight: 600, textTransform: "uppercase", letterSpacing: ".12em", color: C.teal, margin: 0 }}>
          About
        </p>
        <h1 style={{ ...display, fontSize: 40, lineHeight: 1.1, margin: "8px 0 14px", color: C.paper }}>
          A portfolio risk operating system for individual investors
        </h1>
        <p style={{ fontSize: 18, lineHeight: 1.65, color: C.slate, maxWidth: "44em" }}>
          MindMarket turns holdings and market context into a repeatable decision loop: see what
          changed, locate the risk, test a response, save a plan, and return when that decision
          needs review.
        </p>

        <Section title="Why it exists">
          <p>
            Portfolio apps are usually built to show performance and buying power, not risk. Most
            individual investors have no easy way to answer basic questions: how much could this
            portfolio fall in a bad month, which few holdings drive that risk, and how much
            leverage is really embedded in the account. Even when a risk report exists, it rarely
            tells the investor what to inspect next or remembers the decision. MindMarket exists to
            make the analysis readable, testable, and reviewable.
          </p>
        </Section>

        <Section title="How it works">
          <p>
            Today prioritizes the active portfolio. Analyze connects Overview, Drivers, Stress
            Test, Action Plan, and History. Research ideas can open a hypothetical portfolio test;
            useful tests can be saved as plans and reviewed through alerts. Every figure — VaR,
            CVaR, drawdown, betas, scenario losses, and the Health Score — is computed
            deterministically. The AI explains available evidence and admits when data is missing
            or stale. You can read the exact rules on the{" "}
            <Link href="/methodology/health-score" style={{ color: C.teal, textDecoration: "none" }}>
              Health Score methodology
            </Link>{" "}
            and the{" "}
            <Link href="/methodology/regime-model" style={{ color: C.teal, textDecoration: "none" }}>
              market risk-state model card
            </Link>
            .
          </p>
        </Section>

        <Section title="Limitations">
          <ul style={{ paddingLeft: 20, margin: 0 }}>
            <li style={{ marginTop: 6 }}>
              It is educational analytics, <strong style={{ color: C.paper }}>not</strong> investment,
              tax, legal, or financial advice, and never a buy/sell recommendation.
            </li>
            <li style={{ marginTop: 6 }}>
              Estimates are built from daily price history and are US-equity-centric; they cannot
              see private assets, held-away accounts, or fundamentals with no data.
            </li>
            <li style={{ marginTop: 6 }}>
              Market data can be delayed, cached, or unavailable, and short history or illiquid
              names make any risk estimate less reliable — the product surfaces that as data-quality
              caveats.
            </li>
          </ul>
        </Section>

        <Section title="Where the data comes from">
          <p>
            Prices and history are from Yahoo Finance (with a fallback provider), fundamentals and
            analyst data from Financial Modeling Prep, institutional filings from SEC EDGAR, and
            macro series from FRED and the US Treasury. Every external number is shown with its
            source and freshness. AI explanations are generated by large language models
            through a configured model provider over those already-computed numbers.
          </p>
        </Section>

        <Section title="Privacy &amp; security">
          <p>
            Your holdings and scores are private to your account, protected by row-level security
            at the database. The app runs behind Cloudflare with TLS; analytics are limited to
            product-usage events and never include your tickers, amounts, or prompts. See the{" "}
            <Link href="/legal/privacy" style={{ color: C.teal, textDecoration: "none" }}>
              Privacy Policy
            </Link>{" "}
            for the full detail, including how to export or delete your data.
          </p>
        </Section>

        <Section title="Who operates it">
          <p>
            MindMarket is built and operated by an independent developer (zhengbrody). You can
            reach the operator through{" "}
            <a
              href="https://github.com/zhengbrody"
              rel="noopener noreferrer"
              style={{ color: C.teal, textDecoration: "none" }}
            >
              GitHub
            </a>
            .
          </p>
        </Section>

        <div style={{ display: "flex", gap: 14, flexWrap: "wrap", margin: "40px 0 22px" }}>
          <CTA href="/demo-risk-check" lg>
            Explore the risk demo
          </CTA>
          <CTA href="/product" variant="ghost" lg>
            See the product
          </CTA>
        </div>
        <Disclaimer>
          MindMarket is for education and research only. It does not provide investment, tax, legal,
          or financial advice.
        </Disclaimer>
      </article>
    </MarketingShell>
  );
}
