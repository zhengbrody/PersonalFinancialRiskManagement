/**
 * /risk-today — a public, SSR, daily-refreshing market risk read.
 *
 * Leads with the model's VALIDATED signal — the elevated-risk PROBABILITY — and
 * the market inputs that explain it, rendered as real server HTML. It is a
 * probability-ranking
 * signal, NOT a 4-class verdict (on 4-class accuracy the model loses to a
 * persistence baseline), and NOT a price/return forecast. When the model tier is
 * inactive, data is stale, or drift is flagged, the backend degrades and the page
 * shows deterministic market context only. Numbers are deterministic from the
 * backend; the LLM is not involved. Context only — never advice.
 *
 * SSR prose (RegimeReadout) is crawlable. The full live market desk deliberately
 * lives on /markets so this page has one clear job. The page never 500s.
 */

import Link from "next/link";
import { MarketingShell } from "@/components/marketing/marketing-shell";
import { MarketPageSwitcher } from "@/components/marketing/market-page-switcher";
import { RegimeReadout, type RegimeSummary } from "@/components/regime-readout";
import { C, display, eyebrow } from "@/components/marketing/theme";
import { SITE_URL, pageMetadata } from "@/lib/site";

// Render on each request, NOT via ISR. The regime data isn't reachable at build
// time (the backend isn't up during CI), so an ISR prerender would bake the
// fail-soft "unavailable" fallback and serve it until the first revalidation —
// i.e. the page would read "unavailable" for ~30 min after every deploy. The
// backend services are already cached (ml 10 min / macro 5 min), so per-request
// SSR is cheap and the page always shows live data.
export const dynamic = "force-dynamic";

export const metadata = pageMetadata({
  title: "Near-Term Market Risk Signal — Risk Today",
  description:
    "An experimental model estimate of the probability that US equities enter an elevated-volatility regime over the next ~2 weeks, with drivers, data confidence, model health, and documented limits. A signal — not a live market desk, price forecast, or advice.",
  path: "/risk-today",
  ogType: "article",
});

const jsonLd = {
  "@context": "https://schema.org",
  "@type": "TechArticle",
  headline: "Market elevated-risk probability — today’s read",
  description:
    "An experimental probability-ranking signal for elevated market-risk pressure over roughly the next two weeks, with model drivers, data confidence, health, and limitations. Not a price or return forecast and not investment advice.",
  url: `${SITE_URL}/risk-today`,
  about: "US equity market volatility regime",
};

async function fetchSummary(): Promise<RegimeSummary | null> {
  // A server component cannot use the browser's same-origin base — it must call
  // the backend over the in-cluster URL. In the compose network the service name
  // `backend` resolves directly (Caddy proxies /api there too), so the default
  // works in prod with zero config; set INTERNAL_API_BASE_URL=http://localhost:8000
  // for local dev. Fail-soft: a public SEO page must never 500 (build-time
  // pre-render, where `backend` is unreachable, just degrades to the fallback).
  const base = process.env.INTERNAL_API_BASE_URL || "http://backend:8000";
  try {
    const res = await fetch(`${base}/api/v1/regime/summary`, { cache: "no-store" });
    if (!res.ok) return null;
    const body = (await res.json()) as { data?: RegimeSummary };
    return body?.data ?? null;
  } catch {
    return null;
  }
}

function xPostUrl(text: string): string {
  return `https://twitter.com/intent/tweet?text=${encodeURIComponent(text)}`;
}

export default async function RiskTodayPage() {
  const summary = await fetchSummary();

  return (
    <MarketingShell>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />
      <main
        style={{
          maxWidth: 920,
          margin: "0 auto",
          padding: "120px 24px 80px",
          display: "flex",
          flexDirection: "column",
          gap: 40,
        }}
      >
        <p
          style={{ ...eyebrow, margin: 0 }}
        >
          Risk Today · model signal · next ~2 weeks
        </p>

        {summary ? (
          <RegimeReadout summary={summary} />
        ) : (
          <h1 style={{ ...display, color: C.paper, fontSize: "clamp(34px,5vw,52px)", fontWeight: 400, margin: 0 }}>
            Market risk read temporarily unavailable
          </h1>
        )}

        {/* actions: post today's read + score your own */}
        <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
          <Link
            href="/demo-risk-check"
            style={{
              padding: "13px 22px",
              borderRadius: 12,
              background: C.ctaBg,
              color: C.ctaFg,
              fontSize: 15,
              fontWeight: 600,
              textDecoration: "none",
            }}
          >
            Test a portfolio against this regime
          </Link>
          {summary && (
            <a
              href={xPostUrl(summary.post_text)}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                padding: "13px 22px",
                borderRadius: 12,
                background: "transparent",
                color: C.paper,
                border: `1px solid ${C.hairStrong}`,
                fontSize: 15,
                fontWeight: 600,
                textDecoration: "none",
              }}
            >
              Post today’s read on X
            </a>
          )}
        </div>

        <MarketPageSwitcher active="signal" />

        <p style={{ color: C.slateDim, fontSize: 12.5, lineHeight: 1.6, margin: 0 }}>
          Educational market context only — not a price forecast and not investment advice.
          The signal, its honest validation metrics, and its limits are on the{" "}
          <Link href="/methodology/regime-model" style={{ color: C.teal, textDecoration: "none" }}>
            model card
          </Link>
          .
        </p>
      </main>
    </MarketingShell>
  );
}
