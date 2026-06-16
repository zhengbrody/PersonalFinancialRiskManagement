/**
 * /product — explains the four pillars (Health Score, Risk Report, Stock
 * Research, Copilot). Server component (SSR/SEO). Crawlable product education
 * so a visitor (and Google) understands MindMarket before signing in.
 */

import type { Metadata } from "next";
import Link from "next/link";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://mindmarket.app";

export const metadata: Metadata = {
  title: "Product — Health Score, Risk Report, Stock Research & Copilot",
  description:
    "MindMarket turns your holdings into a 0–1000 Health Score, an institutional-grade Risk Report, source-backed Stock Research, and an AI Copilot grounded in deterministic risk math.",
  alternates: { canonical: "/product" },
  openGraph: {
    type: "website",
    title: "MindMarket — AI portfolio risk analytics",
    description:
      "Health Score, Risk Report, Stock Research, and an AI Copilot grounded in deterministic risk math — for individual investors.",
    url: `${SITE_URL}/product`,
    siteName: "MindMarket",
    images: ["/og.jpg"],
  },
  twitter: { card: "summary_large_image" },
};

const PILLARS = [
  {
    name: "Portfolio Health Score",
    tag: "0–1000, explained",
    body: "A single 0–1000 score across three dimensions — risk match, risk-adjusted return, and downside protection — with a gauge, the top drivers, and a plain-English explanation of why it moved since your last visit.",
    href: "/learn/portfolio-risk-management",
  },
  {
    name: "Risk Report",
    tag: "Institutional, readable",
    body: "VaR/CVaR, factor exposures, component VaR, a stress-scenario explorer (−10/−20/−30%), per-holding stress losses, concentration, liquidity, and an options/margin cockpit — every figure with its source and freshness.",
    href: "/learn/var-cvar-explained",
  },
  {
    name: "Stock Research",
    tag: "Source-backed",
    body: "A compact dossier: valuation vs peers, growth and profitability quality, the analyst view, and news — each field tagged with its provider and a data-confidence badge. The AI verdict lays out the bull and bear case and what would change the view, never a buy/sell call.",
    href: "/learn/stock-research",
  },
  {
    name: "AI Copilot",
    tag: "Grounded, never invented",
    body: "Ask about your portfolio in plain English. The Copilot answers from vetted, deterministic numbers — it cites its sources and admits when data is missing, instead of inventing confidence.",
    href: "/learn",
  },
];

export default function ProductPage() {
  const softwareLd = {
    "@context": "https://schema.org",
    "@type": "SoftwareApplication",
    name: "MindMarket",
    applicationCategory: "FinanceApplication",
    operatingSystem: "Web",
    url: `${SITE_URL}/product`,
    description:
      "AI portfolio risk analytics for individual investors: Health Score, Risk Report, Stock Research, and a Copilot grounded in deterministic risk math.",
  };

  return (
    <div className="mx-auto max-w-3xl space-y-10 py-4">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(softwareLd) }}
      />
      <header className="space-y-3">
        <p className="text-xs font-medium uppercase tracking-widest text-primary">Product</p>
        <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">
          Understand the risk you already own before adding more
        </h1>
        <p className="text-lg text-muted-foreground">
          MindMarket turns your holdings into a clear, source-backed risk cockpit — the same kind of
          analytics institutions use, made readable for individual investors. Every number is
          computed from real data; the AI only explains it, never invents it.
        </p>
      </header>

      <div className="grid gap-4 sm:grid-cols-2">
        {PILLARS.map((p) => (
          <Link
            key={p.name}
            href={p.href}
            className="block rounded-xl border border-border bg-card p-5 transition hover:border-primary/40 hover:bg-accent"
          >
            <p className="text-[10px] font-medium uppercase tracking-widest text-primary">{p.tag}</p>
            <p className="mt-1 text-lg font-semibold">{p.name}</p>
            <p className="mt-1.5 text-sm text-muted-foreground">{p.body}</p>
          </Link>
        ))}
      </div>

      <section className="space-y-3 rounded-xl border border-border bg-muted/20 p-6">
        <h2 className="text-xl font-semibold tracking-tight">The rule we don&apos;t break</h2>
        <p className="text-foreground/90">
          Scores, VaR, betas, scenario losses, and valuations are computed deterministically in
          Python from market data. The AI is only allowed to explain, rank, and summarize those
          numbers — it can never invent a figure or a price target. Where a data source is missing or
          stale, the product says so instead of guessing.
        </p>
      </section>

      <div className="flex flex-col gap-3 sm:flex-row">
        <Link
          href="/signup"
          className="rounded-md bg-primary px-5 py-2.5 text-center text-sm font-medium text-primary-foreground hover:bg-primary/90"
        >
          Create free account
        </Link>
        <Link
          href="/learn"
          className="rounded-md border border-border px-5 py-2.5 text-center text-sm hover:bg-accent"
        >
          Learn the concepts
        </Link>
      </div>

      <p className="text-xs text-muted-foreground">Educational analytics — not investment advice.</p>
    </div>
  );
}
