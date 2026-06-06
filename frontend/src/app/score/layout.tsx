import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Portfolio Health Score",
  description:
    "Run a portfolio health score with risk match, risk-adjusted return, downside protection, Sharpe ratio, volatility, max drawdown, VaR, and CVaR.",
  alternates: {
    canonical: "/score",
  },
  openGraph: {
    title: "Portfolio Health Score | MindMarket",
    description:
      "Score a portfolio with deterministic risk math and plain-English AI explanations.",
    url: "/score",
  },
};

export default function ScoreLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return children;
}
