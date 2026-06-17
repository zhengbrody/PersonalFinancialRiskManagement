"use client";

/**
 * MindMarket — animated marketing landing (V2).
 *
 * Port of the design handoff prototype: an always-dark, premium
 * ("Citadel × Robinhood") anonymous marketing view. Zero new deps — motion is
 * CSS transitions + IntersectionObserver + requestAnimationFrame.
 *
 * Rendered full-bleed by SiteShell (no app header) for anonymous visitors; it
 * owns its own fixed nav + footer. Reads var(--font-display) (Instrument Serif,
 * wired in layout.tsx) for headlines and var(--font-geist-mono) for numbers.
 * The root carries `dark` so the embedded <MacroSnapshot/> (which uses theme
 * tokens) resolves the dark palette regardless of the market-hours theme.
 *
 * Colors are intentional marketing literals (distinct from the app .dark
 * tokens); they're centralised in C below.
 */

import { useEffect, useRef, useState, type ReactNode, type CSSProperties } from "react";
import Link from "next/link";
import { Icon, type IconName } from "@/components/ui/icon";
import { MacroSnapshot } from "@/components/macro-snapshot";

/* palette ------------------------------------------------------------------ */
const C = {
  ink: "#07090C",
  panel: "#10161D",
  paper: "#F8FAFC",
  slate: "#AAB4C2",
  teal: "#2FA7BC",
  tealDeep: "#0B7285",
  gold: "#E0AE2A",
  up: "#38D39F",
  down: "#FF6B6B",
  hair: "rgba(255,255,255,0.09)",
  hairStrong: "rgba(255,255,255,0.16)",
};
const display: CSSProperties = { fontFamily: "var(--font-display, Georgia, serif)" };
const mono: CSSProperties = {
  fontFamily: "var(--font-geist-mono, ui-monospace, monospace)",
  fontVariantNumeric: "tabular-nums",
};

/* SEO — preserved from the prior landing (global Org/SoftwareApp JSON-LD lives
   in layout.tsx; these add the product offers + FAQ rich result). */
const PRODUCT_JSON_LD = {
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  name: "MindMarket",
  applicationCategory: "FinanceApplication",
  operatingSystem: "Web",
  url: "https://mindmarket.app/",
  description:
    "AI portfolio risk analytics for individual investors, including portfolio health score, VaR, CVaR, stress tests, factor exposure, and live US rates data.",
  offers: [
    { "@type": "Offer", name: "Free", price: "0", priceCurrency: "USD" },
    { "@type": "Offer", name: "Basic", price: "10", priceCurrency: "USD" },
  ],
};
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

/* helpers ------------------------------------------------------------------ */
const reducedMotion = () =>
  typeof window === "undefined" ||
  !window.matchMedia ||
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;

function useReveal<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [seen, setSeen] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    // No IntersectionObserver (SSR/jsdom) or reduced motion → show final state.
    if (typeof IntersectionObserver === "undefined" || reducedMotion()) {
      setSeen(true);
      return;
    }
    const io = new IntersectionObserver(
      (es) =>
        es.forEach((e) => {
          if (e.isIntersecting) {
            setSeen(true);
            io.disconnect();
          }
        }),
      { threshold: 0.16 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return { ref, seen };
}

function Reveal({ children, delay = 0 }: { children: ReactNode; delay?: number }) {
  const { ref, seen } = useReveal<HTMLDivElement>();
  return (
    <div
      ref={ref}
      style={{
        opacity: seen ? 1 : 0,
        transform: seen ? "none" : "translateY(24px)",
        transition: `opacity .9s cubic-bezier(.16,1,.3,1) ${delay}s, transform .9s cubic-bezier(.16,1,.3,1) ${delay}s`,
      }}
    >
      {children}
    </div>
  );
}

/** Count a number up to `to` once `start` flips true. */
function useCountUp(to: number, start: boolean, dur = 1500) {
  const [v, setV] = useState(0);
  useEffect(() => {
    if (!start) return;
    if (reducedMotion() || typeof requestAnimationFrame === "undefined") {
      setV(to);
      return;
    }
    let raf = 0;
    const t0 = performance.now();
    const tick = (now: number) => {
      const p = Math.min(1, (now - t0) / dur);
      setV(to * (1 - Math.pow(1 - p, 3)));
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [to, start, dur]);
  return v;
}

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
const TICKERS: [string, string, number][] = [
  ["NVDA", "172.41", 2.84], ["AAPL", "228.07", 0.62], ["MSFT", "461.20", 1.1],
  ["TSLA", "241.93", -3.17], ["SPY", "548.02", 0.41], ["TLT", "89.55", -0.41],
  ["AMZN", "201.30", 1.55], ["META", "612.88", 2.02], ["GOOGL", "178.44", -0.74],
  ["NFLX", "915.10", 0.93], ["AMD", "168.22", -1.21], ["BND", "72.19", 0.08],
];
const fmtUsd = (n: number) => (n < 0 ? "−$" : "$") + Math.abs(Math.round(n)).toLocaleString("en-US");

/* buttons (marketing-local treatment) ------------------------------------- */
function CTA({
  children,
  variant = "primary",
  href = "#",
  lg,
}: {
  children: ReactNode;
  variant?: "primary" | "ghost";
  href?: string;
  lg?: boolean;
}) {
  const base: CSSProperties = {
    display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 8,
    fontWeight: 500, borderRadius: lg ? 12 : 10, height: lg ? 52 : 44, padding: lg ? "0 28px" : "0 20px",
    fontSize: lg ? 16 : 15, border: "1px solid transparent", cursor: "pointer",
    transition: "transform .15s, box-shadow .25s, background .2s", whiteSpace: "nowrap", textDecoration: "none",
  };
  const v =
    variant === "primary"
      ? { background: C.paper, color: "#0A0D11", boxShadow: "0 10px 30px -10px rgba(224,174,42,.35)" }
      : { background: "rgba(255,255,255,0.04)", color: C.paper, borderColor: C.hairStrong };
  const style = { ...base, ...v };
  // Internal routes → next/link; in-page anchors → plain <a>.
  if (href.startsWith("/")) {
    return (
      <Link href={href} style={style}>
        {children}
      </Link>
    );
  }
  return (
    <a href={href} style={style}>
      {children}
    </a>
  );
}

/* ───────────────────────────────────────────────────────────────────────── */
export function MarketingLandingV2() {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 12);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <div
      className="dark"
      style={{
        background: C.ink, color: C.paper,
        fontFamily: "var(--font-geist-sans, system-ui, sans-serif)", overflowX: "hidden",
      }}
    >
      <script
        type="application/ld+json"
        suppressHydrationWarning
        dangerouslySetInnerHTML={{ __html: JSON.stringify(PRODUCT_JSON_LD) }}
      />
      <script
        type="application/ld+json"
        suppressHydrationWarning
        dangerouslySetInnerHTML={{ __html: JSON.stringify(FAQ_JSON_LD) }}
      />
      <Nav scrolled={scrolled} />
      <Hero />
      <Ticker />
      <MacroBand />
      <Stats />
      <Demo />
      <Pillars />
      <Steps />
      <ClosingCTA />
      <LearnRow />
      <Footer />
    </div>
  );
}

/* nav ---------------------------------------------------------------------- */
function Nav({ scrolled }: { scrolled: boolean }) {
  return (
    <nav
      style={{
        position: "fixed", insetInline: 0, top: 0, zIndex: 50, display: "flex", alignItems: "center",
        justifyContent: "space-between", padding: scrolled ? "12px 32px" : "16px 32px",
        background: scrolled ? "rgba(7,9,12,0.72)" : "transparent",
        backdropFilter: scrolled ? "blur(14px)" : "none",
        borderBottom: `1px solid ${scrolled ? C.hair : "transparent"}`, transition: "all .3s",
      }}
    >
      <a
        href="#top"
        style={{
          display: "flex", alignItems: "center", gap: 10, fontWeight: 600, fontSize: 15,
          color: C.paper, textDecoration: "none", letterSpacing: "-0.02em",
        }}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/logo-mark.svg" alt="" width={26} height={26} style={{ borderRadius: 7 }} />
        MindMarket
      </a>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <div className="mm-nav-links" style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {[
            ["How it works", "#how"],
            ["Live demo", "#demo"],
            ["Why us", "#why"],
          ].map(([l, href]) => (
            <a
              key={l}
              href={href}
              style={{ color: C.slate, fontSize: 14, padding: "8px 14px", borderRadius: 8, textDecoration: "none" }}
            >
              {l}
            </a>
          ))}
        </div>
        <CTA variant="ghost" href="/login">
          Sign in
        </CTA>
        <CTA href="/signup">Get started</CTA>
      </div>
    </nav>
  );
}

/* hero --------------------------------------------------------------------- */
function Hero() {
  const [started, setStarted] = useState(false);
  useEffect(() => {
    const id = setTimeout(() => setStarted(true), 350);
    return () => clearTimeout(id);
  }, []);
  const score = useCountUp(612, started, 1600);
  const dims = [useCountUp(5.4, started, 1600), useCountUp(7.1, started, 1600), useCountUp(4.2, started, 1600)];

  const R = 92, CX = 120, CY = 120, arc = Math.PI * R, frac = score / 1000;
  const ang = Math.PI * (1 - frac);

  return (
    <header id="top" style={{ position: "relative", padding: "150px 32px 80px", maxWidth: 1200, margin: "0 auto" }}>
      <Glow style={{ width: 620, height: 620, top: -120, right: -160, background: "radial-gradient(circle, rgba(47,167,188,.20), transparent 65%)" }} />
      <Glow style={{ width: 460, height: 460, bottom: -160, left: -120, background: "radial-gradient(circle, rgba(224,174,42,.12), transparent 65%)" }} />
      <div className="mm-hero-grid" style={{ display: "grid", gridTemplateColumns: "1.05fr 0.95fr", gap: 56, alignItems: "center" }}>
        <div>
          <Reveal>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 8, fontSize: 12, fontWeight: 500, textTransform: "uppercase", letterSpacing: ".18em", color: C.teal, marginBottom: 22 }}>
              <span style={{ width: 7, height: 7, borderRadius: "50%", background: C.up }} /> Live · US market open
            </span>
          </Reveal>
          <Reveal delay={0.08}>
            <h1 style={{ ...display, margin: "0 0 24px", fontWeight: 400, fontSize: "clamp(44px,5.6vw,78px)", lineHeight: 1.02, letterSpacing: "-0.01em" }}>
              Know your portfolio&apos;s risk <em style={{ fontStyle: "italic", color: C.gold }}>before</em> the market tests it.
            </h1>
          </Reveal>
          <Reveal delay={0.16}>
            <p style={{ maxWidth: "30em", fontSize: "clamp(16px,1.5vw,19px)", lineHeight: 1.6, color: C.slate, margin: "0 0 32px" }}>
              Connect your holdings and get an institutional-grade risk read in seconds — a 0–1000 Health Score, real VaR and stress tests, explained in plain English. The math hedge funds pay $40k a year for, made simple.
            </p>
          </Reveal>
          <Reveal delay={0.24}>
            <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
              <CTA href="/signup" lg>Score my portfolio — free</CTA>
              <CTA href="#demo" variant="ghost" lg>See a live demo</CTA>
            </div>
            <p style={{ marginTop: 18, fontSize: 13, color: "rgba(170,180,194,.75)" }}>No credit card · numbers are computed, never invented.</p>
          </Reveal>
        </div>

        <div style={{ position: "relative" }}>
          <FloatChip style={{ top: 128, left: -42 }} label="1-day VaR 95%" value="−2.52%" />
          <FloatChip style={{ bottom: 92, right: -34 }} label="Annualized vol" value="24.3%" />
          <Reveal delay={0.08}>
            <div style={{ borderRadius: 22, border: `1px solid ${C.hair}`, background: "linear-gradient(180deg, rgba(255,255,255,0.045), rgba(255,255,255,0.012))", boxShadow: "0 40px 90px -40px rgba(0,0,0,.8)", padding: "26px 26px 22px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                <span style={{ fontSize: 12, textTransform: "uppercase", letterSpacing: ".15em", color: C.slate }}>Portfolio Health Score</span>
                <span style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: ".08em", color: C.gold, border: "1px solid rgba(224,174,42,.4)", background: "rgba(224,174,42,.1)", padding: "4px 9px", borderRadius: 999 }}>Watch</span>
              </div>
              <div style={{ position: "relative" }}>
                <svg viewBox="0 0 240 138" style={{ display: "block", width: "100%", height: "auto" }}>
                  <defs>
                    <linearGradient id="mmArc" x1="0" y1="0" x2="1" y2="0">
                      <stop offset="0" stopColor={C.down} /><stop offset="0.5" stopColor="#FFC24B" /><stop offset="1" stopColor={C.up} />
                    </linearGradient>
                  </defs>
                  <path d="M28 120 A92 92 0 0 1 212 120" fill="none" stroke="rgba(255,255,255,0.09)" strokeWidth={16} strokeLinecap="round" />
                  <path d="M28 120 A92 92 0 0 1 212 120" fill="none" stroke="url(#mmArc)" strokeWidth={16} strokeLinecap="round" strokeDasharray={arc} strokeDashoffset={arc * (1 - frac)} />
                  <circle r={9} fill="#fff" stroke={C.ink} strokeWidth={3} cx={CX + R * Math.cos(ang)} cy={CY - R * Math.sin(ang)} />
                </svg>
                <div style={{ position: "absolute", insetInline: 0, bottom: 6, textAlign: "center" }}>
                  <div style={{ ...mono, fontSize: 56, fontWeight: 600, lineHeight: 1, color: "#FFC24B" }}>{Math.round(score)}</div>
                  <div style={{ fontSize: 14, color: C.slate, marginTop: 4 }}>/ 1000 · health band</div>
                </div>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 10, marginTop: 12 }}>
                {[["Risk match", dims[0]], ["Risk-adj. return", dims[1]], ["Downside prot.", dims[2]]].map(([l, v]) => (
                  <div key={l as string} style={{ textAlign: "center", borderRadius: 12, background: "rgba(255,255,255,0.03)", border: `1px solid ${C.hair}`, padding: "10px 6px" }}>
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
    <div className="mm-float-chip" style={{ position: "absolute", zIndex: 2, borderRadius: 13, border: `1px solid ${C.hairStrong}`, background: "rgba(16,22,29,.82)", backdropFilter: "blur(8px)", padding: "11px 14px", boxShadow: "0 20px 40px -20px rgba(0,0,0,.9)", ...style }}>
      <div style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: ".14em", color: C.slate }}>{label}</div>
      <div style={{ ...mono, fontSize: 17, fontWeight: 600, marginTop: 2, color: "#FFC24B" }}>{value}</div>
    </div>
  );
}

/* ticker ------------------------------------------------------------------- */
function Ticker() {
  const items = [...TICKERS, ...TICKERS];
  return (
    <div style={{ overflow: "hidden", borderBlock: `1px solid ${C.hair}`, background: "rgba(255,255,255,0.015)" }}>
      <div style={{ display: "inline-flex", gap: 40, padding: "9px 0", whiteSpace: "nowrap", ...mono, fontSize: 12.5, animation: "mm-scroll 38s linear infinite" }}>
        {items.map(([t, p, d], i) => (
          <span key={i} style={{ color: C.slate }}>
            <b style={{ color: C.paper, margin: "0 6px 0 8px" }}>{t}</b>${p}{" "}
            <span style={{ color: d >= 0 ? C.up : C.down }}>{d >= 0 ? "+" : ""}{d.toFixed(2)}%</span>
          </span>
        ))}
      </div>
      <style>{`@keyframes mm-scroll{to{transform:translateX(-50%)}}`}</style>
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
            <div style={{ ...mono, fontSize: "clamp(32px,3.4vw,46px)", fontWeight: 600, letterSpacing: "-0.02em", background: "linear-gradient(180deg,#fff,#9fb0c0)", WebkitBackgroundClip: "text", backgroundClip: "text", color: "transparent" }}>
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
                border: `1px solid ${shock === sh ? C.teal : C.hairStrong}`, background: shock === sh ? C.teal : "rgba(255,255,255,0.03)", color: shock === sh ? "#04121a" : C.paper,
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
          <div style={{ borderRadius: 22, border: `1px solid ${C.hair}`, background: "linear-gradient(180deg, rgba(255,255,255,0.045), rgba(255,255,255,0.012))", padding: 26 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 16 }}>
              <span style={{ fontSize: 12, textTransform: "uppercase", letterSpacing: ".15em", color: C.slate }}>What drives the risk</span>
              <span style={{ ...mono, fontSize: 12, color: C.slate }}>share of total VaR</span>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 11 }}>
              {SAMPLE.map((h) => <BarRow key={h.t} t={h.t} pct={(h.varPct / maxVar) * 100} value={`${h.varPct}%`} animate={seen} />)}
            </div>
            <div style={{ marginTop: 20, padding: "14px 16px", borderRadius: 12, border: "1px solid rgba(224,174,42,.28)", background: "rgba(224,174,42,.07)" }}>
              <div style={{ fontSize: 14, fontWeight: 600, color: "#FFC24B" }}>Watch — concentrated in high-beta tech</div>
              <div style={{ fontSize: 13.5, color: C.slate, marginTop: 4, lineHeight: 1.55 }}>Top 4 names are ~72% of the book. The 10% Treasury sleeve is the only real downside cushion.</div>
            </div>
          </div>
        </Reveal>
      </div>
    </Band>
  );
}

function BarRow({ t, pct, value, red, animate }: { t: string; pct: number; value: string; red?: boolean; animate: boolean }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
      <span style={{ width: 56, ...mono, fontSize: 11, letterSpacing: ".04em", color: C.paper, border: `1px solid ${C.hair}`, background: "rgba(255,255,255,0.04)", padding: "3px 7px", borderRadius: 5, textAlign: "center" }}>{t}</span>
      <div style={{ flex: 1, height: 9, borderRadius: 999, background: "rgba(255,255,255,0.07)", overflow: "hidden" }}>
        <div style={{ height: "100%", width: animate ? `${pct}%` : 0, borderRadius: 999, background: red ? "linear-gradient(90deg,#7a1f1f,#FF6B6B)" : `linear-gradient(90deg,${C.tealDeep},${C.teal})`, transition: "width 1s cubic-bezier(.16,1,.3,1)" }} />
      </div>
      <span style={{ width: 44, textAlign: "right", ...mono, fontSize: 12, color: red ? C.down : C.slate }}>{value}</span>
    </div>
  );
}

/* pillars ------------------------------------------------------------------ */
function Pillars() {
  const cards: { ic: IconName; h: string; p: string; m: string }[] = [
    { ic: "score-gauge", h: "Portfolio Health Score", p: "One 0–1000 number for how risk-appropriate your portfolio really is — across three institutional dimensions you can act on.", m: "Risk Match · Risk-Adj. Return · Downside" },
    { ic: "volatility", h: "Institutional risk metrics", p: "Monte-Carlo VaR & CVaR, six-factor betas, component VaR, stress tests and drawdown — the math the pros use, on your account.", m: "VaR 95 / 99 · factor betas · stress" },
    { ic: "trend-up", h: "Live market context", p: "Real Fed Funds, CPI, and the US Treasury curve, streamed live — so you score against the regime that actually exists today.", m: "FRED · US Treasury · hourly" },
  ];
  return (
    <Band id="why">
      <Reveal><p style={eyebrow}>Why MindMarket</p></Reveal>
      <Reveal delay={0.08}><h2 style={secTitle}>Real risk math — <em style={{ fontStyle: "italic", color: C.gold }}>not LLM guesswork.</em></h2></Reveal>
      <div className="mm-pillars" style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 20, marginTop: 44 }}>
        {cards.map((c, i) => (
          <Reveal key={c.h} delay={i * 0.08}>
            <div style={{ borderRadius: 18, border: `1px solid ${C.hair}`, background: "linear-gradient(180deg, rgba(255,255,255,0.035), rgba(255,255,255,0.008))", padding: 26, height: "100%" }}>
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
              <div style={{ ...mono, fontSize: 13, fontWeight: 600, color: C.ink, background: C.gold, width: 30, height: 30, borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 16 }}>{i + 1}</div>
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
        <div style={{ position: "relative", borderRadius: 28, overflow: "hidden", border: `1px solid ${C.hair}`, background: "linear-gradient(160deg, #0C1117, #07090C)", padding: "72px 40px", textAlign: "center" }}>
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

function Footer() {
  return (
    <footer style={{ padding: "48px 32px 60px", borderTop: `1px solid ${C.hair}` }}>
      <div style={{ maxWidth: 1200, margin: "0 auto", display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 18 }}>
        <a href="#top" style={{ display: "flex", alignItems: "center", gap: 10, fontWeight: 600, color: C.paper, textDecoration: "none" }}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/logo-mark.svg" alt="" width={26} height={26} style={{ borderRadius: 7 }} />MindMarket
        </a>
        <p style={{ fontSize: 12.5, color: "rgba(170,180,194,.65)", maxWidth: "46em", lineHeight: 1.5 }}>
          MindMarket provides educational portfolio analytics and software demonstrations. It does not provide investment, tax, legal, or financial advice. Sample figures are illustrative for a fixed demo book, not live prices.
        </p>
      </div>
    </footer>
  );
}

/* shared section bits ------------------------------------------------------ */
function Band({ children, id }: { children: ReactNode; id?: string }) {
  return (
    <section id={id} style={{ borderTop: `1px solid ${C.hair}` }}>
      <div style={{ maxWidth: 1200, margin: "0 auto", padding: "96px 32px" }}>{children}</div>
    </section>
  );
}
const eyebrow: CSSProperties = { fontSize: 12, fontWeight: 500, textTransform: "uppercase", letterSpacing: ".18em", color: C.teal, margin: "0 0 14px" };
const secTitle: CSSProperties = { ...display, fontWeight: 400, fontSize: "clamp(30px,3.6vw,46px)", lineHeight: 1.08, letterSpacing: "-0.01em", margin: 0 };

export default MarketingLandingV2;
