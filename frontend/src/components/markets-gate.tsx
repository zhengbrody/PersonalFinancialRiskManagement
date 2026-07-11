"use client";

/**
 * /markets auth gate: anonymous visitors get a marketing-style intro (premium,
 * market-synced, with a LIVE public preview of the regime + macro and a sign-in
 * CTA) — consistent with the other pre-login pages; signed-in users get the full
 * live markets desk. While auth resolves we show the intro (the crawlable
 * default + a fine public state). SiteShell renders /markets full-bleed for the
 * anon case (see FULL_BLEED handling there).
 */

import { useAuth } from "@/lib/auth-context";
import { MarketRegime } from "@/components/market-regime";
import { RegimeContext } from "@/components/regime-context";
import { MarketSeason } from "@/components/market-season";
import { MarketMovers } from "@/components/market-movers";
import { MarketNews } from "@/components/market-news";
import { PortfolioSentiment } from "@/components/portfolio-sentiment";
import { MacroSnapshot } from "@/components/macro-snapshot";
import { MarketingShell } from "@/components/marketing/marketing-shell";
import { C } from "@/components/marketing/theme";
import {
  Band,
  CTA,
  CTABox,
  Em,
  Eyebrow,
  IconChip,
  MarketingHero,
  SecTitle,
} from "@/components/marketing/primitives";
import type { IconName } from "@/components/ui/icon";

export function MarketsGate() {
  const { user, configured } = useAuth();
  return configured && user ? <MarketsView /> : <MarketsIntro />;
}

/** Signed-in: the full live markets desk (the original page body). */
function MarketsView() {
  return (
    <div className="space-y-10">
      <header className="space-y-1">
        <h1 className="text-3xl font-semibold tracking-tight">Markets</h1>
        <p className="text-sm text-muted-foreground">
          The risk climate at a glance — volatility, sentiment, the curve, and macro. All free,
          public data.
        </p>
      </header>

      <MarketRegime />
      <RegimeContext />
      <MarketSeason />
      <MarketMovers />
      <PortfolioSentiment />
      <MarketNews />
      <MacroSnapshot />
    </div>
  );
}

const PILLARS: { icon: IconName; h: string; p: string }[] = [
  {
    icon: "trend-up",
    h: "Market regime",
    p: "VIX, the Fear & Greed gauge, and the yield-curve shape distilled into one risk-on / risk-off read of the day.",
  },
  {
    icon: "volatility",
    h: "Sector movers",
    p: "Live gainers, losers, and unusual-volume names across sectors — where the money is actually moving.",
  },
  {
    icon: "factors",
    h: "Macro + news",
    p: "Fed Funds, CPI, the US Treasury curve, and the macro headlines that move them — sourced and dated.",
  },
];

/** Anonymous: marketing intro + a real, live public preview of the desk. */
function MarketsIntro() {
  return (
    <MarketingShell>
      <MarketingHero
        eyebrow="Markets"
        title={
          <>
            Read the risk climate — <Em>before</Em> you trade
          </>
        }
        lede="VIX, the Fear & Greed gauge, the US Treasury curve, and live macro — the regime that actually exists today. Free and public; sign in to sync it to your own portfolio."
      >
        <div style={{ display: "flex", gap: 14, flexWrap: "wrap", marginTop: 30 }}>
          <CTA href="/signup" lg>
            Open the markets desk — free
          </CTA>
          <CTA href="/login" variant="ghost" lg>
            Sign in
          </CTA>
        </div>
      </MarketingHero>

      <Band>
        <Eyebrow>Live right now · public data</Eyebrow>
        <div style={{ marginTop: 16, display: "flex", flexDirection: "column", gap: 22 }}>
          <MarketRegime />
          <MacroSnapshot />
        </div>
      </Band>

      <Band>
        <Eyebrow>What the desk gives you</Eyebrow>
        <SecTitle>
          Read the regime, <Em>not the noise.</Em>
        </SecTitle>
        <div
          className="mm-pillars"
          style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 20, marginTop: 40 }}
        >
          {PILLARS.map((c) => (
            <div
              key={c.h}
              style={{
                borderRadius: 18,
                border: `1px solid ${C.hair}`,
                background: C.cardGrad,
                padding: 26,
                height: "100%",
              }}
            >
              <IconChip name={c.icon} />
              <h3 style={{ fontSize: 19, margin: "16px 0 8px", letterSpacing: "-0.01em", color: C.paper }}>
                {c.h}
              </h3>
              <p style={{ fontSize: 14.5, lineHeight: 1.6, color: C.slate, margin: 0 }}>{c.p}</p>
            </div>
          ))}
        </div>
      </Band>

      <Band>
        <CTABox
          headline="Want this synced to your portfolio?"
          lede="Sign in to see how today's regime hits YOUR holdings — sector exposure, per-name sentiment, and stress scenarios."
        >
          <CTA href="/signup">Analyze my portfolio</CTA>
          <CTA href="/research" variant="ghost">
            Research a stock
          </CTA>
        </CTABox>
      </Band>
    </MarketingShell>
  );
}
