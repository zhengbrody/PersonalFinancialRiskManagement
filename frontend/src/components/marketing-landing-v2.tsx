"use client";

/**
 * MindMarket — animated marketing landing (V2).
 *
 * A premium, editorial anonymous marketing view. Market-synced:
 * the --mm-* palette (via the C tokens) flips light/dark with the app theme, so
 * it's light during the trading day and dark overnight. Zero new deps — motion
 * is CSS transitions + IntersectionObserver + rAF (shared with the other
 * pre-login pages via components/marketing/*).
 *
 * Rendered full-bleed by SiteShell (no app header) for anonymous visitors; the
 * shared <MarketingShell/> owns the fixed nav + footer + themed background. This
 * file is just the landing's body sections + its SEO JSON-LD.
 */

import Link from "next/link";
import { useEffect, useState, type CSSProperties } from "react";
import { isUsTradingHours } from "@/lib/market-hours";
import { MacroSnapshot } from "@/components/macro-snapshot";
import { MarketingShell } from "@/components/marketing/marketing-shell";
import { C, display, mono, eyebrow, secTitle } from "@/components/marketing/theme";
import { Reveal, useReveal } from "@/components/marketing/motion";
import { CTA, Band } from "@/components/marketing/primitives";
import {
  ProductSurfaceGrid,
  RiskOsPreview,
  RiskWorkflow,
} from "@/components/marketing/risk-os-story";
import { track } from "@/lib/analytics";
import { ANALYTICS_EVENTS } from "@/lib/analytics-events";
import { LiveTape } from "@/components/marketing/live-tape";
import { StickyMobileCTA } from "@/components/marketing/sticky-mobile-cta";
import { PRODUCT_FAQS } from "@/lib/product-story";

/* SEO — the authoritative Organization + SoftwareApplication JSON-LD ships on
   every page from layout.tsx; the homepage adds only this FAQ rich result (no
   duplicate SoftwareApplication). */
const FAQ_JSON_LD = {
  "@context": "https://schema.org",
  "@type": "FAQPage",
  mainEntity: PRODUCT_FAQS.map((item) => ({
    "@type": "Question",
    name: item.question,
    acceptedAnswer: { "@type": "Answer", text: item.answer },
  })),
};

const LEARN_LINKS = [
  { href: "/portfolio-risk-management", label: "Personal portfolio risk management" },
  { href: "/ai-portfolio-analysis", label: "AI portfolio analysis" },
  { href: "/portfolio-var-stress-testing", label: "VaR & stress testing explained" },
  { href: "/portfolio-stress-test", label: "Stress-test your portfolio" },
  { href: "/stock-portfolio-concentration-risk", label: "Concentration risk in stock portfolios" },
  { href: "/margin-risk-calculator", label: "Margin risk calculator" },
  { href: "/robinhood-margin-risk", label: "Margin risk on Robinhood" },
  { href: "/sample-risk-report", label: "Sample risk report" },
  { href: "/about", label: "About MindMarket" },
];

/* data --------------------------------------------------------------------- */
const SAMPLE = [
  { t: "NVDA", w: 0.22, b: 1.75, varPct: 31 },
  { t: "AAPL", w: 0.2, b: 1.2, varPct: 19 },
  { t: "TSLA", w: 0.12, b: 1.9, varPct: 18 },
  { t: "MSFT", w: 0.18, b: 1.1, varPct: 16 },
  { t: "SPY", w: 0.18, b: 1.0, varPct: 11 },
  { t: "TLT", w: 0.1, b: -0.25, varPct: 5 },
];
const NOTIONAL = 100_000;
const fmtUsd = (n: number) => (n < 0 ? "−$" : "$") + Math.abs(Math.round(n)).toLocaleString("en-US");

/* ───────────────────────────────────────────────────────────────────────── */
export function MarketingLandingV2() {
  useEffect(() => {
    track(ANALYTICS_EVENTS.landing_viewed);
  }, []);
  return (
    <MarketingShell>
      <script
        type="application/ld+json"
        suppressHydrationWarning
        dangerouslySetInnerHTML={{ __html: JSON.stringify(FAQ_JSON_LD) }}
      />
      <Hero />
      <LiveTape />
      <MacroBand />
      <Stats />
      <Demo />
      <OperatingSystem />
      <Steps />
      <Faq />
      <ClosingCTA />
      <LearnRow />
      <StickyMobileCTA />
    </MarketingShell>
  );
}

/* hero --------------------------------------------------------------------- */
function Hero() {
  // Honest session chip — same SSR-safe pattern as <MarketStatusBar>: null on
  // the server/prerender (neutral label), real open/closed state post-mount.
  const [marketOpen, setMarketOpen] = useState<boolean | null>(null);
  useEffect(() => {
    const tick = () => setMarketOpen(isUsTradingHours());
    tick();
    const id = setInterval(tick, 60_000);
    return () => clearInterval(id);
  }, []);
  return (
    <header id="top" style={{ position: "relative", padding: "150px 32px 80px", maxWidth: 1200, margin: "0 auto" }}>
      <Glow style={{ width: 620, height: 620, top: -120, right: -160, background: `radial-gradient(circle, ${C.glowTeal}, transparent 65%)` }} />
      <Glow style={{ width: 460, height: 460, bottom: -160, left: -120, background: `radial-gradient(circle, ${C.glowGold}, transparent 65%)` }} />
      <div className="mm-hero-grid" style={{ display: "grid", gridTemplateColumns: "1.05fr 0.95fr", gap: 56, alignItems: "center" }}>
        <div>
          <Reveal>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 8, fontSize: 12, fontWeight: 500, textTransform: "uppercase", letterSpacing: ".18em", color: C.teal, marginBottom: 22 }}>
              <span style={{ width: 7, height: 7, borderRadius: "50%", background: marketOpen === false ? C.slateDim : C.up }} />
              {marketOpen === null
                ? "US markets"
                : marketOpen
                  ? "Live · US market open"
                  : "US market closed · reopens 9:30 ET"}
            </span>
          </Reveal>
          <Reveal delay={0.08}>
            <h1 style={{ ...display, margin: "0 0 24px", fontWeight: 400, fontSize: "clamp(44px,5.6vw,78px)", lineHeight: 1.02, letterSpacing: "-0.01em" }}>
              Know what changed. <em style={{ fontStyle: "italic", color: C.gold }}>Test</em> what matters. Keep a risk plan.
            </h1>
          </Reveal>
          <Reveal delay={0.16}>
            <p style={{ maxWidth: "30em", fontSize: "clamp(16px,1.5vw,19px)", lineHeight: 1.6, color: C.slate, margin: "0 0 32px" }}>
              MindMarket is a Portfolio Risk OS for individual investors. Review today&apos;s priorities, trace risk in Analyze, test changes without touching real holdings, save a plan, and revisit it when conditions change.
            </p>
          </Reveal>
          <Reveal delay={0.24}>
            <div data-hero-cta style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
              <CTA
                href="/demo-risk-check"
                lg
                onClick={() => track(ANALYTICS_EVENTS.hero_cta_clicked, { target: "demo" })}
              >
                Explore the interactive demo
              </CTA>
              <CTA
                href="/signup"
                variant="ghost"
                lg
                onClick={() => track(ANALYTICS_EVENTS.hero_cta_clicked, { target: "signup" })}
              >
                Create my risk workspace
              </CTA>
            </div>
            <p style={{ marginTop: 18, fontSize: 13, color: C.slateDim }}>No sign-in for the demo · sample data is clearly labeled · risk numbers are computed, never invented.</p>
          </Reveal>
        </div>

        <Reveal delay={0.08}>
          <RiskOsPreview />
        </Reveal>
      </div>
    </header>
  );
}

function Glow({ style }: { style: CSSProperties }) {
  return <div aria-hidden style={{ position: "absolute", borderRadius: "50%", filter: "blur(80px)", pointerEvents: "none", zIndex: 0, ...style }} />;
}
/* live macro context (real data via MacroSnapshot) ------------------------- */
function MacroBand() {
  return (
    <Band>
      <Reveal>
        <p style={eyebrow}>Live market context</p>
      </Reveal>
      <Reveal delay={0.08}>
        <div style={{ marginTop: 16 }}>
          <MacroSnapshot />
        </div>
      </Reveal>
    </Band>
  );
}

/* stats -------------------------------------------------------------------- */
function Stats() {
  const vals = [5, 10000, 6, 1];
  const labels = ["Connected decision stages", "Monte-Carlo paths per run", "Factor groups measured", "Active portfolio context"];
  return (
    <Band>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 24 }} className="mm-pillars">
        {vals.map((v, i) => (
          <div key={i}>
            <div style={{ ...mono, fontSize: "clamp(32px,3.4vw,46px)", fontWeight: 600, letterSpacing: "-0.02em", background: C.statGrad, WebkitBackgroundClip: "text", backgroundClip: "text", color: "transparent" }}>
              {v.toLocaleString("en-US")}
            </div>
            <div style={{ fontSize: 14, color: C.slate, marginTop: 6 }}>{labels[i]}</div>
          </div>
        ))}
      </div>
    </Band>
  );
}

/* demo --------------------------------------------------------------------- */
function Demo() {
  const [shock, setShock] = useState(-10);
  const { ref, seen } = useReveal<HTMLDivElement>();
  const maxVar = Math.max(...SAMPLE.map((h) => h.varPct));
  const s = shock / 100;
  const loss = SAMPLE.reduce((a, h) => a + NOTIONAL * h.w * h.b * s, 0);
  const per = SAMPLE.map((h) => ({ t: h.t, loss: NOTIONAL * h.w * h.b * s })).sort((a, b) => a.loss - b.loss).slice(0, 3);
  const worst = Math.min(...per.map((h) => h.loss));

  return (
    <Band id="demo">
      <Reveal><p style={eyebrow}>Try it — no sign-in</p></Reveal>
      <Reveal delay={0.08}><h2 style={secTitle}>Move the crash slider. <em style={{ fontStyle: "italic", color: C.gold }}>Watch every number react.</em></h2></Reveal>
      <div ref={ref} className="mm-demo-grid" style={{ display: "grid", gridTemplateColumns: "0.95fr 1.05fr", gap: 40, alignItems: "center", marginTop: 40 }}>
        <div>
          <p style={{ color: C.slate, fontSize: 16, lineHeight: 1.6, margin: "0 0 4px" }}>
            A tech-tilted <b style={{ color: C.paper }}>$100,000</b> sample book, scored by the same engine your portfolio would use. Pick a market drop — the estimated loss and the holdings driving it update instantly.
          </p>
          <div style={{ display: "flex", gap: 10, margin: "18px 0" }}>
            {[-5, -10, -20, -30].map((sh) => (
              <button key={sh} onClick={() => setShock(sh)} style={{
                ...mono, fontSize: 15, fontWeight: 600, padding: "10px 16px", borderRadius: 10, cursor: "pointer",
                border: `1px solid ${shock === sh ? C.teal : C.hairStrong}`, background: shock === sh ? C.teal : C.surfaceFaint, color: shock === sh ? "#fff" : C.paper,
              }}>{sh}%</button>
            ))}
          </div>
          <div style={{ borderRadius: 18, border: `1px solid ${C.hair}`, background: C.panel, padding: 26 }}>
            <div style={{ fontSize: 12, textTransform: "uppercase", letterSpacing: ".15em", color: C.slate }}>Estimated portfolio impact</div>
            <div style={{ ...mono, fontSize: "clamp(38px,4.6vw,58px)", fontWeight: 600, color: C.down, lineHeight: 1.05, margin: "6px 0 4px" }}>{fmtUsd(loss)}</div>
            <div style={{ fontSize: 13, color: C.slate }}>{((loss / NOTIONAL) * 100).toFixed(1)}% of a $100,000 book · first-order beta × shock</div>
            <div style={{ marginTop: 18, display: "flex", flexDirection: "column", gap: 11 }}>
              {per.map((h) => (
                <BarRow key={h.t} t={h.t} pct={worst < 0 ? (h.loss / worst) * 100 : 0} value={fmtUsd(h.loss)} red animate={seen} />
              ))}
            </div>
          </div>
        </div>
        <Reveal delay={0.08}>
          <div style={{ borderRadius: 22, border: `1px solid ${C.hair}`, background: C.cardGrad, padding: 26 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 16 }}>
              <span style={{ fontSize: 12, textTransform: "uppercase", letterSpacing: ".15em", color: C.slate }}>What drives the risk</span>
              <span style={{ ...mono, fontSize: 12, color: C.slate }}>share of total VaR</span>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 11 }}>
              {SAMPLE.map((h) => <BarRow key={h.t} t={h.t} pct={(h.varPct / maxVar) * 100} value={`${h.varPct}%`} animate={seen} />)}
            </div>
            <div style={{ marginTop: 20, padding: "14px 16px", borderRadius: 12, border: "1px solid rgba(224,174,42,.28)", background: "rgba(224,174,42,.07)" }}>
              <div style={{ fontSize: 14, fontWeight: 600, color: C.gold }}>Watch — concentrated in high-beta tech</div>
              <div style={{ fontSize: 13.5, color: C.slate, marginTop: 4, lineHeight: 1.55 }}>Top 4 names are ~72% of the book. The 10% Treasury sleeve is the only real downside cushion.</div>
            </div>
          </div>
        </Reveal>
      </div>
      <Reveal delay={0.12}>
        <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 14, marginTop: 32 }}>
          <CTA href="/demo-risk-check">Open the full demo cockpit →</CTA>
          <span style={{ fontSize: 13.5, color: C.slate }}>
            Health score, diagnosis, and a one-click high-growth stress toggle — still no sign-in.
          </span>
        </div>
      </Reveal>
    </Band>
  );
}

function BarRow({ t, pct, value, red, animate }: { t: string; pct: number; value: string; red?: boolean; animate: boolean }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
      <span style={{ width: 56, ...mono, fontSize: 11, letterSpacing: ".04em", color: C.paper, border: `1px solid ${C.hair}`, background: C.surfaceFaint, padding: "3px 7px", borderRadius: 5, textAlign: "center" }}>{t}</span>
      <div style={{ flex: 1, height: 9, borderRadius: 999, background: C.track, overflow: "hidden" }}>
        <div style={{ height: "100%", width: animate ? `${pct}%` : 0, borderRadius: 999, background: red ? "linear-gradient(90deg,#7a1f1f,#FF6B6B)" : `linear-gradient(90deg,${C.tealDeep},${C.teal})`, transition: "width 1s cubic-bezier(.16,1,.3,1)" }} />
      </div>
      <span style={{ width: 44, textAlign: "right", ...mono, fontSize: 12, color: red ? C.down : C.slate }}>{value}</span>
    </div>
  );
}

/* operating surfaces ------------------------------------------------------- */
function OperatingSystem() {
  return (
    <Band id="product">
      <Reveal><p style={eyebrow}>One operating system</p></Reveal>
      <Reveal delay={0.08}><h2 style={secTitle}>Analysis becomes a <em style={{ fontStyle: "italic", color: C.gold }}>repeatable decision loop.</em></h2></Reveal>
      <Reveal delay={0.12}>
        <p style={{ color: C.slate, fontSize: 16, lineHeight: 1.65, maxWidth: "44em", margin: "16px 0 36px" }}>
          Today tells you where to start. Analyze keeps the quantitative work together. Research, tests, plans, alerts, and Copilot carry the same active-portfolio context forward.
        </p>
      </Reveal>
      <ProductSurfaceGrid />
    </Band>
  );
}

/* steps -------------------------------------------------------------------- */
function Steps() {
  return (
    <Band id="workflow">
      <Reveal><p style={eyebrow}>How it works</p></Reveal>
      <Reveal delay={0.08}><h2 style={secTitle}>From signal to saved decision — without changing a holding.</h2></Reveal>
      <div style={{ marginTop: 40 }}><RiskWorkflow /></div>
    </Band>
  );
}

function Faq() {
  return (
    <Band id="questions">
      <p style={eyebrow}>Questions</p>
      <h2 style={secTitle}>Clear boundaries make better risk decisions.</h2>
      <div style={{ display: "grid", gap: 12, marginTop: 34 }}>
        {PRODUCT_FAQS.map((item) => (
          <details key={item.question} style={{ borderRadius: 14, border: `1px solid ${C.hair}`, background: C.surfaceFaint, padding: "16px 18px" }}>
            <summary style={{ color: C.paper, cursor: "pointer", fontWeight: 600 }}>{item.question}</summary>
            <p style={{ color: C.slate, fontSize: 14.5, lineHeight: 1.65, margin: "12px 0 0" }}>{item.answer}</p>
          </details>
        ))}
      </div>
    </Band>
  );
}

/* closing CTA -------------------------------------------------------------- */
function ClosingCTA() {
  return (
    <Band id="cta">
      <Reveal>
        <div style={{ position: "relative", borderRadius: 28, overflow: "hidden", border: `1px solid ${C.hair}`, background: `linear-gradient(160deg, ${C.panel}, ${C.ink})`, padding: "72px 40px", textAlign: "center" }}>
          <svg viewBox="0 0 1200 300" preserveAspectRatio="none" aria-hidden style={{ position: "absolute", inset: 0, zIndex: 0, opacity: 0.5, width: "100%", height: "100%" }}>
            <path d="M0 230 L240 230 L330 196 L470 214 L620 150 L760 176 L920 96 L1200 40" fill="none" stroke={C.gold} strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round" opacity={0.85} />
            <circle cx={1200} cy={40} r={5} fill={C.gold} />
          </svg>
          <div style={{ position: "relative", zIndex: 1 }}>
            <h2 style={{ ...display, fontWeight: 400, fontSize: "clamp(32px,4.4vw,56px)", lineHeight: 1.05, margin: "0 0 18px" }}>
              Turn portfolio analysis into a <em style={{ fontStyle: "italic", color: C.gold }}>habit you can review.</em>
            </h2>
            <p style={{ color: C.slate, fontSize: 17, margin: "0 auto 30px", maxWidth: "36em" }}>Create a portfolio, open Today, and follow a connected path from priority to test to saved plan.</p>
            <CTA href="/signup" lg>Create my risk workspace</CTA>
          </div>
        </div>
      </Reveal>
    </Band>
  );
}

/* learn (SEO internal links) ----------------------------------------------- */
function LearnRow() {
  return (
    <Band>
      <p style={eyebrow}>Learn portfolio risk</p>
      <ul style={{ listStyle: "none", padding: 0, margin: "16px 0 0", display: "grid", gridTemplateColumns: "repeat(3,minmax(0,1fr))", gap: "6px 28px" }} className="mm-pillars">
        {LEARN_LINKS.map((l) => (
          <li key={l.href}>
            <Link href={l.href} style={{ color: C.slate, fontSize: 14, textDecoration: "none" }}>
              {l.label}
            </Link>
          </li>
        ))}
      </ul>
    </Band>
  );
}

export default MarketingLandingV2;
