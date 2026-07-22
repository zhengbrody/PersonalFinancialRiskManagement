/**
 * /share/risk-card — the visible landing for a shared risk-score card.
 *
 * Server component. It supports a fixed public `?book=` demo and a signed,
 * non-indexed `?token=` card containing coarse bands only. Metadata points at
 * the sibling dynamic OG handler so links unfurl without exposing holdings,
 * identity, exact scores, tickers or dollar values.
 *
 * This page is where a shared click LANDS, so it leads with a "run it on your own
 * portfolio" CTA — that's the viral loop back into the funnel.
 */

import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ScoreGauge } from "@/components/score-gauge";
import { MarketingShell } from "@/components/marketing/marketing-shell";
import { C, display, eyebrow } from "@/components/marketing/theme";
import {
  parseShareBook,
  xIntentUrl,
  linkedInIntentUrl,
  type ShareBand,
  riskFitLabel,
  stressBandLabel,
  titleCase,
  tokenLinkedInIntentUrl,
  tokenXIntentUrl,
} from "@/lib/share-card";
import { resolveShareToken } from "@/lib/share-card-server";

type SP = { searchParams: Promise<{ book?: string; token?: string }> };

const BAND_COLOR: Record<ShareBand, string> = {
  Poor: C.down,
  Watch: C.gold,
  Healthy: C.up,
  Strong: C.up,
};

export async function generateMetadata({ searchParams }: SP): Promise<Metadata> {
  const params = await searchParams;
  if (params.token) {
    try {
      const card = await resolveShareToken(params.token);
      const title = `Portfolio risk profile: ${titleCase(card.score_band)}`;
      const description = "A privacy-preserving portfolio risk profile with no positions, identity, exact score, or dollar values.";
      const image = `/share/risk-card/og?token=${encodeURIComponent(params.token)}`;
      return {
        title,
        description,
        robots: { index: false, follow: false },
        referrer: "no-referrer",
        openGraph: { title, description, images: [{ url: image, width: 1200, height: 630 }] },
        twitter: { card: "summary_large_image", title, description, images: [image] },
      };
    } catch {
      return { title: "Share card not found", robots: { index: false, follow: false }, referrer: "no-referrer" };
    }
  }
  const book = parseShareBook(params.book);
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

export default async function ShareRiskCardPage({ searchParams }: SP) {
  const params = await searchParams;
  if (params.token) {
    try {
      const card = await resolveShareToken(params.token);
      return <RealCard card={card} token={params.token} />;
    } catch {
      notFound();
    }
  }
  const book = parseShareBook(params.book);
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
        <p style={{ ...eyebrow, margin: 0 }}>Portfolio risk X-ray · sample</p>

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

async function RealCard({ card, token }: { card: Awaited<ReturnType<typeof resolveShareToken>>; token: string }) {
  const fields = [
    ["Health band", titleCase(card.score_band)],
    ["Risk fit", riskFitLabel(card.risk_fit)],
    ["Primary risk", titleCase(card.top_risk_category)],
    ["−20% market stress", stressBandLabel(card.stress_band)],
    ["Data confidence", titleCase(card.confidence_label)],
  ];
  return (
    <MarketingShell>
      <main style={{ maxWidth: 760, margin: "0 auto", padding: "120px 24px 80px", display: "flex", flexDirection: "column", gap: 28 }}>
        <p style={{ ...eyebrow, margin: 0 }}>Portfolio risk profile · private by design</p>
        <div style={{ display: "flex", flexDirection: "column", gap: 18, padding: 28, borderRadius: 20, background: C.cardGrad, border: `1px solid ${C.hair}` }}>
          <h1 style={{ ...display, color: C.paper, fontSize: 42, margin: 0 }}>{titleCase(card.score_band)} risk profile</h1>
          <p style={{ color: C.slate, margin: 0, lineHeight: 1.6 }}>Only broad bands are shared. This card contains no holdings, tickers, identity, exact score, or dollar values.</p>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))", gap: 10 }}>
            {fields.map(([label, value]) => <div key={label} style={{ padding: 14, borderRadius: 12, background: C.surfaceFaint, border: `1px solid ${C.hair}` }}><span style={{ color: C.slateDim, fontSize: 11, textTransform: "uppercase" }}>{label}</span><p style={{ color: C.paper, fontSize: 18, margin: "5px 0 0" }}>{value}</p></div>)}
          </div>
          <p style={{ color: C.slateDim, fontSize: 12, margin: 0 }}>As of {card.as_of} · model {card.model_version}</p>
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
          <Link href="/demo-risk-check" style={{ ...shareBtn, background: C.ctaBg, color: C.ctaFg }}>Check my portfolio</Link>
          <a href={tokenXIntentUrl(card, token)} target="_blank" rel="noopener noreferrer" style={shareBtn}>Share on X</a>
          <a href={tokenLinkedInIntentUrl(token)} target="_blank" rel="noopener noreferrer" style={shareBtn}>Share on LinkedIn</a>
        </div>
        <p style={{ color: C.slateDim, fontSize: 12.5, lineHeight: 1.6, margin: 0 }}>Anyone with this link can view these broad bands until it expires automatically. Educational risk information only, not investment advice.</p>
      </main>
    </MarketingShell>
  );
}

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
