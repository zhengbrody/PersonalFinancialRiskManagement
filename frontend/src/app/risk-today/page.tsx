/**
 * /risk-today — a public, SSR, daily-refreshing market risk-state page.
 *
 * Three jobs in one: (1) refreshing SEO content (a trained model's read of the
 * current volatility regime + live VIX/F&G/curve, rendered as real server HTML),
 * (2) a quotable/screenshot artifact (with a one-tap "post today's read"), and
 * (3) a credibility surface for the ML work. Numbers are deterministic from the
 * backend; the LLM is not involved. Context only — never advice.
 *
 * SSR prose (RegimeReadout) is crawlable; the live client desk (MarketRegime +
 * MacroSnapshot) refreshes on the client. The page never 500s — a dead upstream
 * degrades to a graceful "unavailable" state.
 */

import type { Metadata } from "next";
import Link from "next/link";
import { MarketingShell } from "@/components/marketing/marketing-shell";
import { RegimeReadout, type RegimeSummary } from "@/components/regime-readout";
import { MarketRegime } from "@/components/market-regime";
import { MacroSnapshot } from "@/components/macro-snapshot";
import { C, display } from "@/components/marketing/theme";

// Render on each request, NOT via ISR. The regime data isn't reachable at build
// time (the backend isn't up during CI), so an ISR prerender would bake the
// fail-soft "unavailable" fallback and serve it until the first revalidation —
// i.e. the page would read "unavailable" for ~30 min after every deploy. The
// backend services are already cached (ml 10 min / macro 5 min), so per-request
// SSR is cheap and the page always shows live data.
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Today’s Market Risk Regime",
  description:
    "A trained model’s read of the current market risk-state, plus live VIX, Fear & Greed, and the US Treasury yield curve. Updated through the trading day — context, not advice.",
  alternates: { canonical: "/risk-today" },
  openGraph: {
    title: "Today’s Market Risk Regime | MindMarket",
    description:
      "The current market risk-state (calm → stressed) from a trained model, with live VIX, Fear & Greed, and the yield curve.",
    url: "/risk-today",
  },
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
          style={{
            fontSize: 12,
            fontWeight: 500,
            textTransform: "uppercase",
            letterSpacing: ".18em",
            color: C.teal,
            margin: 0,
          }}
        >
          Market risk-state · updated through the trading day
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
            Check your portfolio against this regime
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

        {/* live client desk — refreshes on the client */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <h2 style={{ ...display, color: C.paper, fontSize: 26, fontWeight: 400, margin: 0 }}>
            Live market desk
          </h2>
          <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 16 }}>
            <MarketRegime />
            <MacroSnapshot />
          </div>
        </div>

        <p style={{ color: C.slateDim, fontSize: 12.5, lineHeight: 1.6, margin: 0 }}>
          Educational market context only — not a price forecast and not investment advice.
          The risk-state model is described on{" "}
          <Link href="/learn/stress-testing" style={{ color: C.teal, textDecoration: "none" }}>
            our risk guides
          </Link>
          .
        </p>
      </main>
    </MarketingShell>
  );
}
