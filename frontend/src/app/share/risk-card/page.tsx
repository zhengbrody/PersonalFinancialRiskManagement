/**
 * /share/risk-card — the visible landing for a shared risk-score card.
 *
 * Server component (SSR/crawlable). Reads the fixed `?book=` demo, renders a
 * premium card (reusing <ScoreGauge>), and exports generateMetadata pointing the
 * OG/Twitter image at the sibling dynamic route handler (/share/risk-card/og)
 * so the link unfurls with a real 1200×630 PNG on X/LinkedIn/Slack. The score is
 * a fixed demo constant (never from the query string) — see lib/share-card.ts.
 *
 * This page is where a shared click LANDS, so it leads with a "run it on your own
 * portfolio" CTA — that's the viral loop back into the funnel.
 */

import type { Metadata } from "next";
import Link from "next/link";
import { ScoreGauge } from "@/components/score-gauge";
import { MarketingShell } from "@/components/marketing/marketing-shell";
import { C, display } from "@/components/marketing/theme";
import {
  parseShareBook,
  xIntentUrl,
  linkedInIntentUrl,
  type ShareBand,
} from "@/lib/share-card";

type SP = { searchParams: { book?: string } };

const BAND_COLOR: Record<ShareBand, string> = {
  Poor: C.down,
  Watch: C.gold,
  Healthy: C.up,
  Strong: C.up,
};

export function generateMetadata({ searchParams }: SP): Metadata {
  const book = parseShareBook(searchParams.book);
  const title = `${book.label}: risk score ${book.score}/1000 (${book.band})`;
  const description = book.takeaway;
  const image = `/share/risk-card/og?book=${book.id}`;
  return {
    title,
    description,
    alternates: { canonical: `/share/risk-card?book=${book.id}` },
    openGraph: {
      title,
      description,
      images: [{ url: image, width: 1200, height: 630 }],
    },
    twitter: { card: "summary_large_image", title, description, images: [image] },
  };
}

export default function ShareRiskCardPage({ searchParams }: SP) {
  const book = parseShareBook(searchParams.book);
  const accent = BAND_COLOR[book.band];

  return (
    <MarketingShell>
      <main
        style={{
          maxWidth: 760,
          margin: "0 auto",
          padding: "120px 24px 80px",
          display: "flex",
          flexDirection: "column",
          gap: 28,
        }}
      >
        <p style={{ ...eyebrow }}>Portfolio risk X-ray · sample</p>

        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 20,
            padding: 28,
            borderRadius: 20,
            background: C.cardGrad,
            border: `1px solid ${C.hair}`,
          }}
        >
          <span style={{ color: C.slate, fontSize: 16, fontWeight: 500 }}>{book.label}</span>
          <div style={{ display: "flex", alignItems: "flex-end", flexWrap: "wrap", gap: 14 }}>
            <span style={{ ...display, color: C.paper, fontSize: 88, fontWeight: 400, lineHeight: 1 }}>
              {book.score}
            </span>
            <span style={{ color: C.slate, fontSize: 22, paddingBottom: 12 }}>/ 1000</span>
            <span
              style={{
                marginLeft: 6,
                marginBottom: 16,
                padding: "6px 16px",
                borderRadius: 999,
                background: `${accent}22`,
                color: accent,
                fontSize: 16,
                fontWeight: 700,
              }}
            >
              {book.band}
            </span>
          </div>

          {/* reuse the real product gauge */}
          <div style={{ color: C.paper }}>
            <ScoreGauge score={book.score} />
          </div>

          <p style={{ color: C.paper, fontSize: 18, lineHeight: 1.5, margin: 0 }}>{book.takeaway}</p>

          <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
            {book.dimensions.map((d) => (
              <div
                key={d.label}
                style={{
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  padding: "10px 16px",
                  borderRadius: 12,
                  background: C.surfaceFaint,
                  border: `1px solid ${C.hair}`,
                  minWidth: 96,
                }}
              >
                <span style={{ color: C.paper, fontSize: 20, fontWeight: 600 }}>
                  {d.value.toFixed(1)}
                </span>
                <span style={{ color: C.slateDim, fontSize: 11, marginTop: 2 }}>{d.label}</span>
              </div>
            ))}
          </div>
        </div>

        {/* CTA — the loop back into the funnel */}
        <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
          <Link
            href="/demo-risk-check"
            style={{
              flex: "1 1 240px",
              textAlign: "center",
              padding: "14px 22px",
              borderRadius: 12,
              background: C.ctaBg,
              color: C.ctaFg,
              fontSize: 15,
              fontWeight: 600,
              textDecoration: "none",
            }}
          >
            Run it on my portfolio — free
          </Link>
          <a
            href={xIntentUrl(book)}
            target="_blank"
            rel="noopener noreferrer"
            style={shareBtn}
          >
            Share on X
          </a>
          <a
            href={linkedInIntentUrl(book)}
            target="_blank"
            rel="noopener noreferrer"
            style={shareBtn}
          >
            Share on LinkedIn
          </a>
        </div>

        <p style={{ color: C.slateDim, fontSize: 12.5, lineHeight: 1.6, margin: 0 }}>
          Sample data — illustrative metrics for a fixed demo book, not live prices or
          investment advice. Your own cockpit uses real market data with full source
          provenance. Educational only.
        </p>
      </main>
    </MarketingShell>
  );
}

const eyebrow = {
  fontSize: 12,
  fontWeight: 500,
  textTransform: "uppercase" as const,
  letterSpacing: ".18em",
  color: C.teal,
  margin: 0,
};

const shareBtn = {
  flex: "1 1 140px",
  textAlign: "center" as const,
  padding: "14px 22px",
  borderRadius: 12,
  background: "transparent",
  color: C.paper,
  border: `1px solid ${C.hairStrong}`,
  fontSize: 15,
  fontWeight: 600,
  textDecoration: "none",
};
