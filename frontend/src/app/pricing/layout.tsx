import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Pricing",
  description:
    "MindMarket pricing for AI portfolio risk analytics, portfolio health scores, risk reports, Copilot analysis, and market data.",
  alternates: {
    canonical: "/pricing",
  },
  openGraph: {
    title: "Pricing | MindMarket",
    description:
      "Choose a plan for AI portfolio risk analytics, Health Score, risk reports, and Copilot credits.",
    url: "/pricing",
  },
};

export default function PricingLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return children;
}
