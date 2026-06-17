/**
 * /demo — public, no-auth Demo Risk Check. The fastest path to "I get it":
 * a real, deterministic risk cockpit on a sample book, with a one-click toggle
 * to stress a high-growth portfolio. Server component (SSR/SEO) wrapping the
 * client <SampleCockpit/>; a tiny client ping fires `demo_started` on mount.
 */

import type { Metadata } from "next";
import Link from "next/link";
import { SampleCockpit } from "@/components/sample-cockpit";
import { DemoStartedPing } from "@/components/demo-started-ping";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://mindmarket.app";

export const metadata: Metadata = {
  title: "Demo Risk Check — see your portfolio's hidden risk in 30 seconds",
  description:
    "Try MindMarket's risk cockpit free, no sign-in: score a balanced book, then one-click stress a high-growth portfolio to see concentration, volatility, and crash exposure. Every number is computed, nothing is invented.",
  alternates: { canonical: "/demo" },
  openGraph: {
    type: "website",
    title: "MindMarket — Demo Risk Check",
    description:
      "Score a sample portfolio and stress a high-growth book in 30 seconds — no sign-in. Deterministic risk math, not AI guesswork.",
    url: `${SITE_URL}/demo`,
    siteName: "MindMarket",
    images: ["/og.jpg"],
  },
  twitter: { card: "summary_large_image" },
};

export default function DemoRiskCheckPage() {
  return (
    <div className="mx-auto max-w-3xl space-y-8 py-4">
      <DemoStartedPing />
      <header className="space-y-3">
        <p className="text-xs font-medium uppercase tracking-widest text-primary">Demo Risk Check</p>
        <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">
          See what can break a portfolio — before you add more risk
        </h1>
        <p className="text-lg text-muted-foreground">
          No sign-in. Start with a balanced book, then one-click{" "}
          <span className="font-medium text-foreground">stress a high-growth portfolio</span> to
          see how concentration, volatility, and a tech-and-crypto selloff change the picture.
        </p>
      </header>

      <SampleCockpit />

      <section className="flex flex-col items-start gap-3 rounded-xl border border-border bg-card p-6 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="font-semibold">Want this for your own portfolio?</p>
          <p className="text-sm text-muted-foreground">
            Add your holdings (or import a CSV) and get a real Health Score, risk report, and
            AI copilot — free during beta.
          </p>
        </div>
        <div className="flex shrink-0 gap-2">
          <Link
            href="/signup"
            className="rounded-md bg-primary px-5 py-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            Analyze my portfolio
          </Link>
          <Link
            href="/research"
            className="rounded-md border border-border px-5 py-2.5 text-sm hover:bg-accent"
          >
            Research a stock
          </Link>
        </div>
      </section>

      <p className="text-xs text-muted-foreground">
        Sample data for illustration — not live prices and not investment advice. Your own
        cockpit uses real market data with full source provenance.
      </p>
    </div>
  );
}
