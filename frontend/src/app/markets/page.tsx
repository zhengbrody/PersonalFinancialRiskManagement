import { MarketsGate } from "@/components/markets-gate";
import { pageMetadata } from "@/lib/site";

export const metadata = pageMetadata({
  title: "Markets — Live US Conditions, Sectors & Macro",
  description:
    "See current US market conditions: VIX, Fear & Greed, the Treasury yield curve, sector movers, macro releases, headlines, and source freshness. A live descriptive desk, separate from MindMarket’s near-term risk signal.",
  path: "/markets",
  ogType: "website",
});

/**
 * Public Markets route (Phase 10 port of legacy `3_Markets`). Server component
 * for metadata; the body is an auth gate (<MarketsGate/>): anonymous visitors
 * get a marketing-style intro with a live public preview + sign-in CTA, signed-in
 * users get the full live desk. Near-term model probability stays on
 * /risk-today so the two public surfaces do not duplicate each other.
 */
export default function MarketsPage() {
  return <MarketsGate />;
}
