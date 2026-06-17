/**
 * /learn/[slug] — one educational topic. Server component (SSR): Googlebot sees
 * the full text without hydration. Per-topic metadata + FAQPage + BreadcrumbList
 * JSON-LD. Content lives in lib/learn-content.ts; this file is just the shell.
 */

import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { LEARN_BY_SLUG, LEARN_SLUGS } from "@/lib/learn-content";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://mindmarket.app";

export function generateStaticParams() {
  return LEARN_SLUGS.map((slug) => ({ slug }));
}

export function generateMetadata({ params }: { params: { slug: string } }): Metadata {
  const topic = LEARN_BY_SLUG[params.slug];
  if (!topic) return { title: "Learn" };
  const url = `${SITE_URL}/learn/${topic.slug}`;
  return {
    title: topic.metaTitle,
    description: topic.description,
    alternates: { canonical: `/learn/${topic.slug}` },
    openGraph: {
      type: "article",
      title: topic.metaTitle,
      description: topic.description,
      url,
      siteName: "MindMarket",
      images: ["/og.jpg"],
    },
    twitter: { card: "summary_large_image", title: topic.metaTitle, description: topic.description },
  };
}

export default function LearnTopicPage({ params }: { params: { slug: string } }) {
  const topic = LEARN_BY_SLUG[params.slug];
  if (!topic) notFound();

  const faqLd = {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: topic.faqs.map((f) => ({
      "@type": "Question",
      name: f.q,
      acceptedAnswer: { "@type": "Answer", text: f.a },
    })),
  };
  const breadcrumbLd = {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: [
      { "@type": "ListItem", position: 1, name: "Home", item: SITE_URL },
      { "@type": "ListItem", position: 2, name: "Learn", item: `${SITE_URL}/learn` },
      { "@type": "ListItem", position: 3, name: topic.title, item: `${SITE_URL}/learn/${topic.slug}` },
    ],
  };

  return (
    <article className="mx-auto max-w-3xl space-y-8 py-4">
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(faqLd) }} />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(breadcrumbLd) }}
      />

      <nav className="text-xs text-muted-foreground">
        <Link href="/" className="hover:underline">
          Home
        </Link>{" "}
        ›{" "}
        <Link href="/learn" className="hover:underline">
          Learn
        </Link>{" "}
        › <span className="text-foreground">{topic.title}</span>
      </nav>

      <header className="space-y-3">
        <p className="text-xs font-medium uppercase tracking-widest text-primary">{topic.eyebrow}</p>
        <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">{topic.title}</h1>
        <p className="text-lg text-muted-foreground">{topic.intro}</p>
      </header>

      <div className="space-y-8">
        {topic.sections.map((s, i) => (
          <section key={i} className="space-y-3">
            <h2 className="text-xl font-semibold tracking-tight">{s.heading}</h2>
            {s.paragraphs.map((p, j) => (
              <p key={j} className="leading-relaxed text-foreground/90">
                {p}
              </p>
            ))}
            {s.example && (
              <div className="rounded-lg border border-primary/20 bg-primary/5 p-4">
                <p className="text-xs font-semibold uppercase tracking-wide text-primary">
                  {s.example.label}
                </p>
                <p className="mt-1 text-sm text-foreground/90">{s.example.body}</p>
              </div>
            )}
          </section>
        ))}
      </div>

      {/* CTAs */}
      <div className="flex flex-col gap-3 rounded-xl border border-border bg-card p-6 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="font-semibold">See it on a real book</p>
          <p className="text-sm text-muted-foreground">
            Run a sample portfolio, or score your own in seconds.
          </p>
        </div>
        <div className="flex gap-2">
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

      {/* FAQ */}
      <section className="space-y-4">
        <h2 className="text-xl font-semibold tracking-tight">Frequently asked</h2>
        <div className="divide-y divide-border rounded-lg border border-border">
          {topic.faqs.map((f, i) => (
            <div key={i} className="p-4">
              <p className="font-medium">{f.q}</p>
              <p className="mt-1 text-sm text-muted-foreground">{f.a}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Related */}
      {topic.related.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Keep learning
          </h2>
          <ul className="space-y-1">
            {topic.related.map((slug) => {
              const r = LEARN_BY_SLUG[slug];
              if (!r) return null;
              return (
                <li key={slug}>
                  <Link href={`/learn/${slug}`} className="text-sm text-primary hover:underline">
                    {r.title} →
                  </Link>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      <p className="border-t border-border pt-4 text-xs text-muted-foreground">
        Educational content only — not investment advice, and not a recommendation to buy or sell
        any security. MindMarket helps you measure and understand risk you already own.
      </p>
    </article>
  );
}
