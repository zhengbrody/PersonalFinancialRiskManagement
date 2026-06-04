import type { Metadata } from "next";
import { MarketRegime } from "@/components/market-regime";
import { MarketSeason } from "@/components/market-season";
import { MarketMovers } from "@/components/market-movers";
import { MarketNews } from "@/components/market-news";
import { PortfolioSentiment } from "@/components/portfolio-sentiment";
import { MacroSnapshot } from "@/components/macro-snapshot";

export const metadata: Metadata = {
  title: "Markets · MindMarket",
  description:
    "Live market regime — VIX, Fear & Greed, the US Treasury yield curve, and key macro series. Free, no signup.",
};

/**
 * Public Markets page (Phase 10 port of legacy `3_Markets`).
 *
 * MVP scope: the Market-Regime panel (VIX / Fear & Greed / yield-curve
 * status) + the live macro snapshot (FRED rates + yield curve). The
 * heavier AI-Sentiment / Reddit-FOMO / per-holding news blocks stay on
 * the legacy Streamlit workbench for now (linked below) and land in a
 * later sub-phase.
 */
export default function MarketsPage() {
  return (
    <div className="space-y-10">
      <header className="space-y-1">
        <h1 className="text-3xl font-semibold tracking-tight">Markets</h1>
        <p className="text-sm text-muted-foreground">
          The risk climate at a glance — volatility, sentiment, the curve,
          and macro. All free, public data.
        </p>
      </header>

      <MarketRegime />

      <MarketSeason />

      <MarketMovers />

      <PortfolioSentiment />

      <MarketNews />

      <MacroSnapshot />

      {/* Reddit FOMO monitor still lives in the legacy workbench (needs a paid
          Apify key). Everything else on this page is now ported. */}
      <section className="rounded-lg border border-border bg-muted/30 p-5">
        <h2 className="text-sm font-semibold">Looking for more?</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          The Reddit FOMO monitor lives in the advanced workbench.
        </p>
        <a
          href="/legacy/3_Markets"
          className="mt-3 inline-block rounded-md border border-primary/50 bg-primary/10 px-3 py-1.5 text-sm text-primary hover:bg-primary/20"
        >
          Open advanced Markets workbench →
        </a>
      </section>
    </div>
  );
}
