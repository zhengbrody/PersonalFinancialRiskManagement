/**
 * /learn — the educational hub. Server component (SSR/SEO). Lists every topic
 * with its blurb + an ItemList JSON-LD so the hub is crawlable.
 */

import type { Metadata } from "next";
import Link from "next/link";
import { LEARN_TOPICS } from "@/lib/learn-content";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://mindmarket.app";

export const metadata: Metadata = {
  title: "Learn portfolio risk — plain-English guides for individual investors",
  description:
    "Free, example-led guides to portfolio risk: VaR & CVaR, factor exposure, stress testing, margin risk, options Greeks, and risk-first stock research.",
  alternates: { canonical: "/learn" },
  openGraph: {
    type: "website",
    title: "Learn portfolio risk — MindMarket",
    description:
      "Free, example-led guides to portfolio risk for individual investors: VaR/CVaR, factor exposure, stress testing, margin, options, and stock research.",
    url: `${SITE_URL}/learn`,
    siteName: "MindMarket",
    images: ["/og.jpg"],
  },
  twitter: { card: "summary_large_image" },
};

export default function LearnHubPage() {
  const itemListLd = {
    "@context": "https://schema.org",
    "@type": "ItemList",
    name: "MindMarket Learn — portfolio risk guides",
    itemListElement: LEARN_TOPICS.map((t, i) => ({
      "@type": "ListItem",
      position: i + 1,
      url: `${SITE_URL}/learn/${t.slug}`,
      name: t.title,
    })),
  };

  return (
    <div className="mx-auto max-w-3xl space-y-8 py-4">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(itemListLd) }}
      />
      <header className="space-y-3">
        <p className="text-xs font-medium uppercase tracking-widest text-primary">Learn</p>
        <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">
          Understand the risk you already own
        </h1>
        <p className="text-lg text-muted-foreground">
          Plain-English, example-led guides to portfolio risk — the same concepts the Health Score
          and Risk Report are built on. No jargon, no buy/sell calls.
        </p>
      </header>

      <ul className="grid gap-3 sm:grid-cols-2">
        {LEARN_TOPICS.map((t) => (
          <li key={t.slug}>
            <Link
              href={`/learn/${t.slug}`}
              className="block h-full rounded-xl border border-border bg-card p-5 transition hover:border-primary/40 hover:bg-accent"
            >
              <p className="text-[10px] font-medium uppercase tracking-widest text-primary">
                {t.eyebrow}
              </p>
              <p className="mt-1 font-semibold leading-snug">{t.title}</p>
              <p className="mt-1.5 text-sm text-muted-foreground">{t.description}</p>
            </Link>
          </li>
        ))}
      </ul>

      <div className="rounded-xl border border-border bg-card p-6 text-center">
        <p className="font-semibold">Ready to see it on a portfolio?</p>
        <p className="mt-1 text-sm text-muted-foreground">
          Run a deterministic sample cockpit, or score your own holdings free.
        </p>
        <div className="mt-3 flex justify-center gap-2">
          <Link
            href="/demo-risk-check"
            className="rounded-md border border-border px-4 py-2 text-sm hover:bg-accent"
          >
            Run a sample portfolio
          </Link>
          <Link
            href="/signup"
            className="rounded-md bg-primary px-4 py-2 text-sm text-primary-foreground hover:bg-primary/90"
          >
            Create free account
          </Link>
        </div>
      </div>

      <p className="text-xs text-muted-foreground">
        Educational content only — not investment advice.
      </p>
    </div>
  );
}
