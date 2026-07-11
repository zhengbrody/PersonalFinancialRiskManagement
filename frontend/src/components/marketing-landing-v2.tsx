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

import { useEffect, useState, type CSSProperties } from "react";
import { Icon, type IconName } from "@/components/ui/icon";
import { isUsTradingHours } from "@/lib/market-hours";
import { MacroSnapshot } from "@/components/macro-snapshot";
import { MarketingShell } from "@/components/marketing/marketing-shell";
import { C, display, mono, eyebrow, secTitle } from "@/components/marketing/theme";
import { Reveal, useReveal, useCountUp } from "@/components/marketing/motion";
import { CTA, Band } from "@/components/marketing/primitives";
import { LiveTape } from "@/components/marketing/live-tape";
import { StickyMobileCTA } from "@/components/marketing/sticky-mobile-cta";

/* SEO — the authoritative Organization + SoftwareApplication JSON-LD ships on
   every page from layout.tsx; the homepage adds only this FAQ rich result (no
   duplicate SoftwareApplication). */
const FAQ_JSON_LD = {
  "@context": "https://schema.org",
  "@type": "FAQPage",
  mainEntity: [
    {
      "@type": "Question",
      name: "What does MindMarket measure?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "MindMarket measures portfolio health, volatility, Sharpe ratio, max drawdown, VaR, CVaR, factor exposure, stress-test losses, and live macro context.",
      },
    },
    {
      "@type": "Question",
      name: "Does the AI invent portfolio risk numbers?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "No. Risk numbers are calculated by deterministic Python services. AI explanations only summarize already-computed metrics.",
      },
    },
  ],
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
      <Pillars />
      <Steps />
      <ClosingCTA />
      <LearnRow />
      <StickyMobileCTA />
    </MarketingShell>
  );
}

/* hero --------------------------------------------------------------------- */
function Hero() {
  const [started, setStarted] = useState(false);
  useEffect(() => {
    const id = setTimeout(() => setStarted(true), 350);
    return () => clearTimeout(id);
  }, []);
  // Honest session chip — same SSR-safe pattern as <MarketStatusBar>: null on
  // the server/prerender (neutral label), real open/closed state post-mount.
  const [marketOpen, setMarketOpen] = useState<boolean | null>(null);
  useEffect(() => {
    const tick = () => setMarketOpen(isUsTradingHours());
    tick();
    const id = setInterval(tick, 60_000);
    return () => clearInterval(id);
  }, []);
  const score = useCountUp(612, started, 1600);
  const dims = [useCountUp(5.4, started, 1600), useCountUp(7.1, started, 1600), useCountUp(4.2, started, 1600)];

  const R = 92, CX = 120, CY = 120, arc = Math.PI * R, frac = score / 1000;
  const ang = Math.PI * (1 - frac);

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
              Know your portfolio&apos;s risk <em style={{ fontStyle: "italic", color: C.gold }}>before</em> the market tests it.
            </h1>
          </Reveal>
          <Reveal delay={0.16}>
            <p style={{ maxWidth: "30em", fontSize: "clamp(16px,1.5vw,19px)", lineHeight: 1.6, color: C.slate, margin: "0 0 32px" }}>
              Paste your holdings — or import from your broker — and get a transparent risk X-ray in seconds: a 0–1000 Health Score, real VaR, stress tests, and concentration, explained in plain English. Free, no signup to try.
            </p>
          </Reveal>
          <Reveal delay={0.24}>
            <div data-hero-cta style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
              <CTA href="/demo-risk-check" lg>Try a free risk check</CTA>
              <CTA href="/signup" variant="ghost" lg>Score my portfolio</CTA>
            </div>
            <p style={{ marginTop: 18, fontSize: 13, color: C.slateDim }}>No signup to try · no credit card · numbers are computed, never invented.</p>
          </Reveal>
        </div>

        <div style={{ position: "relative" }}>
          <FloatChip style={{ top: 128, left: -42 }} label="Sample · 1-day VaR 95%" value="−2.52%" />
          <FloatChip style={{ bottom: 92, right: -34 }} label="Sample · annualized vol" value="24.3%" />
          <Reveal delay={0.08}>
            <div style={{ borderRadius: 22, border: `1px solid ${C.hair}`, background: C.cardGrad, boxShadow: "0 40px 90px -40px rgba(0,0,0,.8)", padding: "26px 26px 22px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                <span style={{ fontSize: 12, textTransform: "uppercase", letterSpacing: ".15em", color: C.slate }}>Portfolio Health Score</span>
                <span style={{ display: "inline-flex", gap: 6 }}>
                  <span style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: ".08em", color: C.slate, border: `1px solid ${C.hair}`, padding: "4px 9px", borderRadius: 999 }}>Sample</span>
                  <span style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: ".08em", color: C.gold, border: "1px solid rgba(224,174,42,.4)", background: "rgba(224,174,42,.1)", padding: "4px 9px", borderRadius: 999 }}>Watch</span>
                </span>
              </div>
              <div style={{ position: "relative" }}>
                <svg viewBox="0 0 240 138" style={{ display: "block", width: "100%", height: "auto" }}>
                  <defs>
                    <linearGradient id="mmArc" x1="0" y1="0" x2="1" y2="0">
                      <stop offset="0" stopColor={C.down} /><stop offset="0.5" stopColor={C.gold} /><stop offset="1" stopColor={C.up} />
                    </linearGradient>
                  </defs>
                  <path d="M28 120 A92 92 0 0 1 212 120" fill="none" stroke={C.track} strokeWidth={16} strokeLinecap="round" />
                  <path d="M28 120 A92 92 0 0 1 212 120" fill="none" stroke="url(#mmArc)" strokeWidth={16} strokeLinecap="round" strokeDasharray={arc} strokeDashoffset={arc * (1 - frac)} />
                  <circle r={9} fill={C.paper} stroke={C.ink} strokeWidth={3} cx={CX + R * Math.cos(ang)} cy={CY - R * Math.sin(ang)} />
                </svg>
                <div style={{ position: "absolute", insetInline: 0, bottom: 6, textAlign: "center" }}>
                  <div style={{ ...mono, fontSize: 56, fontWeight: 600, lineHeight: 1, color: C.gold }}>{Math.round(score)}</div>
                  <div style={{ fontSize: 14, color: C.slate, marginTop: 4 }}>/ 1000 · sample book</div>
                </div>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 10, marginTop: 12 }}>
                {[["Risk match", dims[0]], ["Risk-adj. return", dims[1]], ["Downside prot.", dims[2]]].map(([l, v]) => (
                  <div key={l as string} style={{ textAlign: "center", borderRadius: 12, background: C.surfaceFaint, border: `1px solid ${C.hair}`, padding: "10px 6px" }}>
                    <div style={{ ...mono, fontSize: 19, fontWeight: 600 }}>{(v as number).toFixed(1)}</div>
                    <div style={{ fontSize: 10.5, color: C.slate, marginTop: 2 }}>{l as string}</div>
                  </div>
                ))}
              </div>
            </div>
          </Reveal>
        </div>
      </div>
    </header>
  );
}

function Glow({ style }: { style: CSSProperties }) {
  return <div aria-hidden style={{ position: "absolute", borderRadius: "50%", filter: "blur(80px)", pointerEvents: "none", zIndex: 0, ...style }} />;
}
function FloatChip({ style, label, value }: { style: CSSProperties; label: string; value: string }) {
  return (
    <div className="mm-float-chip" style={{ position: "absolute", zIndex: 2, borderRadius: 13, border: `1px solid ${C.hairStrong}`, background: C.chipBg, backdropFilter: "blur(8px)", padding: "11px 14px", boxShadow: "0 20px 40px -20px rgba(0,0,0,.9)", ...style }}>
      <div style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: ".14em", color: C.slate }}>{label}</div>
      <div style={{ ...mono, fontSize: 17, fontWeight: 600, marginTop: 2, color: C.gold }}>{value}</div>
    </div>
  );
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
  const { ref, seen } = useReveal<HTMLDivElement>();
  const vals = [useCountUp(1000, seen), useCountUp(10000, seen), useCountUp(6, seen), useCountUp(30, seen)];
  const labels = ["Point Health Score scale", "Monte-Carlo paths per run", "Risk factors regressed", "To your first score"];
  const suffix = ["", "", "", "s"];
  return (
    <Band>
      <div ref={ref} style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 24 }} className="mm-pillars">
        {vals.map((v, i) => (
          <div key={i}>
            <div style={{ ...mono, fontSize: "clamp(32px,3.4vw,46px)", fontWeight: 600, letterSpacing: "-0.02em", background: C.statGrad, WebkitBackgroundClip: "text", backgroundClip: "text", color: "transparent" }}>
              {Math.round(v).toLocaleString("en-US")}{suffix[i]}
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

/* pillars ------------------------------------------------------------------ */
function Pillars() {
  const cards: { ic: IconName; h: string; p: string; m: string }[] = [
    { ic: "score-gauge", h: "Portfolio Health Score", p: "One 0–1000 number for how risk-appropriate your portfolio really is — across three dimensions you can act on.", m: "Risk Match · Risk-Adj. Return · Downside" },
    { ic: "volatility", h: "Institutional-style risk metrics", p: "Monte-Carlo VaR & CVaR, six-factor betas, component VaR, stress tests and drawdown — deterministic, explainable risk math on your own account.", m: "VaR 95 / 99 · factor betas · stress" },
    { ic: "trend-up", h: "Live market context", p: "Real Fed Funds, CPI, and the US Treasury curve, streamed live — so you score against the regime that actually exists today.", m: "FRED · US Treasury · hourly" },
  ];
  return (
    <Band id="why">
      <Reveal><p style={eyebrow}>Why MindMarket</p></Reveal>
      <Reveal delay={0.08}><h2 style={secTitle}>Real risk math — <em style={{ fontStyle: "italic", color: C.gold }}>not LLM guesswork.</em></h2></Reveal>
      <div className="mm-pillars" style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 20, marginTop: 44 }}>
        {cards.map((c, i) => (
          <Reveal key={c.h} delay={i * 0.08}>
            <div style={{ borderRadius: 18, border: `1px solid ${C.hair}`, background: C.cardGrad, padding: 26, height: "100%" }}>
              <div style={{ width: 46, height: 46, borderRadius: 12, display: "flex", alignItems: "center", justifyContent: "center", background: `linear-gradient(135deg, ${C.teal}, ${C.tealDeep})`, marginBottom: 18, boxShadow: "0 8px 20px -8px rgba(47,167,188,.5)" }}>
                <Icon name={c.ic} style={{ width: 23, height: 23, color: "#06151c" }} />
              </div>
              <h3 style={{ fontSize: 19, margin: "0 0 8px", letterSpacing: "-0.01em" }}>{c.h}</h3>
              <p style={{ fontSize: 14.5, lineHeight: 1.6, color: C.slate, margin: "0 0 14px" }}>{c.p}</p>
              <div style={{ ...mono, fontSize: 12, color: "rgba(170,180,194,.7)", paddingTop: 12, borderTop: `1px solid ${C.hair}` }}>{c.m}</div>
            </div>
          </Reveal>
        ))}
      </div>
    </Band>
  );
}

/* steps -------------------------------------------------------------------- */
function Steps() {
  const steps = [
    ["Add your holdings", "Tickers and shares — average cost optional for P&L. Edit any time. Takes about a minute."],
    ["See your Health Score", "A 0–1000 score plus your single biggest risk, the moment your holdings are in."],
    ["Ask your Copilot", "Plain-English answers about your risk — grounded in your real, computed numbers."],
  ];
  return (
    <Band id="how">
      <Reveal><p style={eyebrow}>How it works</p></Reveal>
      <Reveal delay={0.08}><h2 style={secTitle}>Three minutes to your first score.</h2></Reveal>
      <div className="mm-pillars" style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 20, marginTop: 44 }}>
        {steps.map(([h, p], i) => (
          <Reveal key={h} delay={i * 0.08}>
            <div style={{ borderRadius: 16, border: `1px solid ${C.hair}`, padding: 26, height: "100%" }}>
              <div style={{ ...mono, fontSize: 13, fontWeight: 600, color: "#0B0E11", background: C.gold, width: 30, height: 30, borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 16 }}>{i + 1}</div>
              <h4 style={{ fontSize: 17, margin: "0 0 6px" }}>{h}</h4>
              <p style={{ fontSize: 14, color: C.slate, lineHeight: 1.55, margin: 0 }}>{p}</p>
            </div>
          </Reveal>
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
              See what can hurt your portfolio <em style={{ fontStyle: "italic", color: C.gold }}>before</em> it does.
            </h2>
            <p style={{ color: C.slate, fontSize: 17, margin: "0 auto 30px", maxWidth: "34em" }}>Free during beta — all core features open, no credit card. Your first Health Score is 30 seconds away.</p>
            <CTA href="/signup" lg>Score my portfolio — free</CTA>
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
            {/* Static Caddy-served SEO pages → plain <a>, not next/link. */}
            <a href={l.href} style={{ color: C.slate, fontSize: 14, textDecoration: "none" }}>
              {l.label}
            </a>
          </li>
        ))}
      </ul>
    </Band>
  );
}

export default MarketingLandingV2;
