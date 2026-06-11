import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Market Conditions",
  description:
    "Live US market regime: VIX, Treasury yield curve, Fear & Greed, sector heatmap, top movers, and macro news — the context behind your portfolio's risk.",
  alternates: {
    canonical: "/markets",
  },
  openGraph: {
    title: "Market Conditions | MindMarket",
    description:
      "VIX, yield curve, Fear & Greed, sector heatmap and movers — updated through the trading day.",
    url: "/markets",
  },
};

export default function MarketsLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return children;
}
