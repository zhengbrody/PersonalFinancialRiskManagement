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
    siteName: "MindMarket",
    images: ["/og.jpg"],
  },
  twitter: {
    card: "summary_large_image",
    title: "Pricing | MindMarket",
    description:
      "Plans for AI portfolio risk analytics, Health Score, risk reports, and Copilot credits.",
  },
};

export default function PricingLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return children;
}
