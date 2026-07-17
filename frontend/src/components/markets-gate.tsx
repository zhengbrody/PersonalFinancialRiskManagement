"use client";

/**
 * /markets auth gate: anonymous visitors get a marketing-style intro
 * with a LIVE public preview of current conditions and a sign-in
 * CTA) — consistent with the other pre-login pages; signed-in users get the full
 * live markets desk. While auth resolves we show the intro (the crawlable
 * default + a fine public state). SiteShell renders /markets full-bleed for the
 * anon case (see FULL_BLEED handling there).
 */

import { useAuth } from "@/lib/auth-context";
import Link from "next/link";
import { MarketRegime } from "@/components/market-regime";
import { RegimeContext } from "@/components/regime-context";
import { MarketSeason } from "@/components/market-season";
import { MarketMovers } from "@/components/market-movers";
import { MarketNews } from "@/components/market-news";
import { PortfolioSentiment } from "@/components/portfolio-sentiment";
import { MacroSnapshot } from "@/components/macro-snapshot";
import { MarketingShell } from "@/components/marketing/marketing-shell";
import { MarketPageSwitcher } from "@/components/marketing/market-page-switcher";
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
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="space-y-1">
          <h1 className="text-3xl font-semibold tracking-tight">Markets</h1>
          <p className="text-sm text-muted-foreground">
            What is moving now — volatility, sentiment, rates, sectors, macro, and headlines from
            source-stamped public data.
          </p>
        </div>
        <Link
          href="/risk-today"
          className="text-sm font-medium text-primary underline-offset-4 hover:underline"
        >
          Open the near-term model signal →
        </Link>
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
    h: "Live conditions",
    p: "VIX, the Fear & Greed gauge, and the yield-curve shape describe the market state that exists now — not a forecast.",
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
        eyebrow="Markets · live conditions"
        title={
          <>
            See what is moving <Em>right now.</Em>
          </>
        }
        lede="VIX, the Fear & Greed gauge, the US Treasury curve, sectors, and macro headlines — a descriptive market desk for the conditions that exist today. Use Risk Today separately for the near-term model signal."
      >
        <div style={{ display: "flex", gap: 14, flexWrap: "wrap", marginTop: 30 }}>
          <CTA href="/signup" lg>
            Create risk workspace
          </CTA>
          <CTA href="/login" variant="ghost" lg>
            Sign in
          </CTA>
        </div>
      </MarketingHero>

      <Band>
        <MarketPageSwitcher active="desk" />
      </Band>

      <Band>
        <Eyebrow>Current conditions · source-stamped public data</Eyebrow>
        <div style={{ marginTop: 16, display: "flex", flexDirection: "column", gap: 22 }}>
          <MarketRegime />
          <MacroSnapshot />
        </div>
      </Band>

      <Band>
        <Eyebrow>What the desk gives you</Eyebrow>
        <SecTitle>
          Read what moved, <Em>then decide what to analyze.</Em>
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
          headline="Connect the market regime to the portfolio you actually own."
          lede="Use the same context inside Today and Analyze to understand which holdings, factors, and saved plans deserve review."
        >
          <CTA href="/signup">Create risk workspace</CTA>
          <CTA href="/product#workflow" variant="ghost">
            See the workflow
          </CTA>
        </CTABox>
      </Band>
    </MarketingShell>
  );
}
