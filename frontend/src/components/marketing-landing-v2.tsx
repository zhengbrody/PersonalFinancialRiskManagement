"use client";

import Link from "next/link";
import { useEffect } from "react";
import { MarketingShell } from "@/components/marketing/marketing-shell";
import { CTA } from "@/components/marketing/primitives";
import { SampleComparison } from "@/components/marketing/sample-comparison";
import { ComparisonCapabilities, ProductSurfaceGrid } from "@/components/marketing/risk-os-story";
import { StickyMobileCTA } from "@/components/marketing/sticky-mobile-cta";
import { PRODUCT_FAQS, PRODUCT_POSITIONING } from "@/lib/product-story";
import { track } from "@/lib/analytics";
import { ANALYTICS_EVENTS } from "@/lib/analytics-events";
import styles from "@/components/marketing/public-experience.module.css";

const FAQ_JSON_LD = {
  "@context": "https://schema.org", "@type": "FAQPage",
  mainEntity: PRODUCT_FAQS.map(({ question, answer }) => ({
    "@type": "Question", name: question, acceptedAnswer: { "@type": "Answer", text: answer },
  })),
};
const QUESTIONS = [
  { title: "Where is my risk concentrated?", body: "Several tickers can still share the same risk. Inspect position sizes and common drivers, then see which exposures deserve a closer look.", href: "/stock-portfolio-concentration-risk", link: "Understand concentration" },
  { title: "What changes if I reduce a position?", body: "Compare a hypothetical change with your current portfolio. See the difference in exposure, cash and financing before deciding what to do.", href: "/demo-risk-check", link: "Test a sample change" },
  { title: "What can I trust in this analysis?", body: "Inspect the evidence, assumptions and data limitations behind a result. A missing input should be visible—not disguised as a confident answer.", href: "/methodology/health-score", link: "Explore the methodology" },
];
const LEARN_LINKS = [
  ["/portfolio-risk-management", "Personal portfolio risk management"],
  ["/ai-portfolio-analysis", "AI portfolio analysis"],
  ["/portfolio-var-stress-testing", "VaR & stress testing explained"],
  ["/portfolio-stress-test", "Stress-test your portfolio"],
  ["/margin-risk-calculator", "Margin risk calculator"],
  ["/robinhood-margin-risk", "Margin risk on Robinhood"],
  ["/sample-risk-report", "Sample risk report"],
  ["/about", "Why MindMarket exists"],
];

/** Public body only. Home's existing auth switch and crawlable default stay intact. */
export function MarketingLandingV2() {
  useEffect(() => { track(ANALYTICS_EVENTS.landing_viewed); }, []);
  return (
    <MarketingShell>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(FAQ_JSON_LD) }} />
      <div className={styles.page}>
        <header className={styles.hero} data-hero-cta>
          <div>
            <p className={styles.eyebrow}>Your portfolio. A clearer perspective.</p>
            <h1 className={styles.headline}>Understand your risk <span>before your next move.</span></h1>
            <p className={styles.lede}>{PRODUCT_POSITIONING.description}</p>
            <div className={styles.actions}>
              <CTA href="#sample" lg onClick={() => track(ANALYTICS_EVENTS.hero_cta_clicked, { target: "demo" })}>Try a sample portfolio ↓</CTA>
              <CTA href="/signup?next=%2Fportfolios%2Fnew" variant="ghost" lg onClick={() => track(ANALYTICS_EVENTS.hero_cta_clicked, { target: "signup" })}>Analyze my portfolio</CTA>
            </div>
            <p className={styles.hint}>No sign-in for the sample. No trades placed.</p>
            <p className={styles.hint}>Built for individual investors who want to understand their stocks, ETFs, options and financing—not just watch a balance.</p>
          </div>
          <div id="sample" style={{ scrollMarginTop: 96 }}><SampleComparison /></div>
        </header>
        <section className={styles.section} aria-labelledby="questions-title">
          <p className={styles.eyebrow}>Start with your question</p>
          <h2 id="questions-title">Less guesswork.<br />More understanding.</h2>
          <div className={styles.grid}>{QUESTIONS.map((question, i) => (
            <article className={styles.card} key={question.title}>
              <span className={styles.number}>0{i + 1}</span><h3>{question.title}</h3><p>{question.body}</p>
              <Link className={styles.link} href={question.href}>{question.link} →</Link>
            </article>
          ))}</div>
        </section>
        <section className={styles.section} id="how-it-works">
          <p className={styles.eyebrow}>From a question to a checked scenario</p>
          <h2>Know the trade-offs.<br />Keep the decision yours.</h2>
          <div className={styles.grid}>
            <article className={styles.card}><span className={styles.number}>01 / UNDERSTAND</span><h3>Bring your portfolio into focus.</h3><p>Add your holdings, select your active portfolio, and inspect the risks and data gaps that matter to that account.</p></article>
            <article className={styles.card}><span className={styles.number}>02 / COMPARE</span><h3>Test before changing anything.</h3><p>Specify a supported hypothetical adjustment. Compare the result against the same starting portfolio, with assumptions visible.</p></article>
            <article className={styles.card}><span className={styles.number}>03 / DECIDE</span><h3>Keep a plan, not just an answer.</h3><p>When saving is available, confirm an eligible comparison to keep a draft. It preserves that calculation—not an automatic monitoring task or an instruction to a broker.</p></article>
          </div>
        </section>
        <section className={styles.section} aria-labelledby="comparison-scope-title">
          <p className={styles.eyebrow}>Inside your signed-in workspace</p>
          <h2 id="comparison-scope-title">Different questions.<br />Clearly defined tests.</h2>
          <p className={styles.lede}>The sample above illustrates one idea. Your signed-in tools use portfolio data, with different coverage and methods for each workflow.</p>
          <ComparisonCapabilities />
        </section>
        <section className={`${styles.section} ${styles.trust}`} id="evidence">
          <div><p className={styles.eyebrow}>Evidence before confidence</p><h2>See how the answer was made.</h2><p className={styles.lede}>Risk figures are computed. AI helps explain the available evidence. Neither removes uncertainty.</p><Link className={styles.link} href="/methodology/health-score">Read the methodology →</Link></div>
          <ul>
            <li><strong>Trace the inputs.</strong><br />Inspect sources, dates and assumptions where available.</li>
            <li><strong>Know what is missing.</strong><br />Unavailable or stale data can limit the analysis.</li>
            <li><strong>Stay in control.</strong><br />Tests do not change holdings. Saving a comparison requires confirmation.</li>
            <li><strong>Understand the boundaries.</strong><br />Options and margin need additional inputs. Not every strategy or adjustment is supported.</li>
          </ul>
        </section>
        <section className={styles.section}>
          <p className={styles.eyebrow}>One connected workspace</p><h2>Go deeper when you need to.</h2>
          <p className={styles.lede}>Start with a priority in Today. Explore it in Analyze, investigate a ticker in Research, or ask Copilot to explain the evidence.</p>
          <ProductSurfaceGrid />
          <p style={{ marginTop: 28 }}><Link href="/markets" className={styles.link}>Looking for market context? Explore Markets →</Link></p>
        </section>
        <section className={styles.section} aria-labelledby="faq-title">
          <p className={styles.eyebrow}>Before you begin</p><h2 id="faq-title">A few useful answers.</h2>
          {PRODUCT_FAQS.map(({ question, answer }) => <details key={question} className={styles.faq}><summary>{question}</summary><p>{answer}</p></details>)}
          <div className={styles.learn}>{LEARN_LINKS.map(([href, label]) => <Link className={styles.link} key={href} href={href}>{label}</Link>)}</div>
        </section>
        <section className={styles.closing}>
          <p className={styles.eyebrow}>Clarity comes before action</p><h2>Your next move starts<br />with understanding.</h2>
          <div className={styles.actions}><CTA href="/signup?next=%2Fportfolios%2Fnew" lg>Analyze my portfolio</CTA><CTA href="/demo-risk-check" variant="ghost" lg>Explore the full demo</CTA></div>
          <p className={styles.hint}>Educational risk analytics. Not investment advice.</p>
        </section>
      </div>
      <StickyMobileCTA />
    </MarketingShell>
  );
}
