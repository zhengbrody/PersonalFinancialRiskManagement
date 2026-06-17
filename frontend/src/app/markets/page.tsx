import type { Metadata } from "next";
import { MarketsGate } from "@/components/markets-gate";

export const metadata: Metadata = {
  title: "US Markets & Macro",
  description:
    "Live market regime — VIX, Fear & Greed, the US Treasury yield curve, and key macro series. Free, no signup.",
  alternates: {
    canonical: "/markets",
  },
  openGraph: {
    title: "US Markets & Macro | MindMarket",
    description:
      "Track VIX, market regime, sector movers, macro news, FRED rates, and the US Treasury yield curve.",
    url: "/markets",
  },
};

/**
 * Public Markets route (Phase 10 port of legacy `3_Markets`). Server component
 * for metadata; the body is an auth gate (<MarketsGate/>): anonymous visitors
 * get a marketing-style intro with a live public preview + sign-in CTA, signed-in
 * users get the full live desk. Reddit FOMO still lives in the legacy workbench.
 */
export default function MarketsPage() {
  return <MarketsGate />;
}
