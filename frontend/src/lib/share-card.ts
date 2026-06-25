/**
 * Shareable "risk-score card" — the single source of truth for the public
 * /share/risk-card page AND its /share/risk-card/opengraph-image route.
 *
 * Framework-free + pure (no React, no client imports) so the server OG route can
 * import it safely. The card's SCORE comes from a constant keyed by `book`,
 * NEVER from the query string — a hand-edited `?score=9999` cannot forge a fake
 * number on this public, un-authed, cache-poisonable surface. That keeps the
 * product-wide "never invent a number" invariant on the shareable artifact.
 *
 * SHARE_BOOKS mirrors the BALANCED/GROWTH demo books in
 * components/sample-cockpit.tsx; share-card.test.ts asserts they stay in sync
 * (score + band) so they can't silently drift.
 */

export type ShareBookId = "balanced" | "growth";
export type ShareBand = "Poor" | "Watch" | "Healthy" | "Strong";

export type ShareBook = {
  id: ShareBookId;
  label: string; // human portfolio label shown on the card
  score: number; // 0–1000 health score (the demo constant)
  band: ShareBand; // derived from `score` (asserted vs scoreBand in the test)
  takeaway: string; // one-line headline insight
  dimensions: { label: string; value: number }[]; // 0–10 dimension scores
};

export const DEFAULT_SHARE_BOOK: ShareBookId = "growth";

export const SHARE_BOOKS: Record<ShareBookId, ShareBook> = {
  balanced: {
    id: "balanced",
    label: "Balanced portfolio",
    score: 784,
    band: "Healthy",
    takeaway:
      "Diversified across stocks, bonds, gold, and cash — moderate, broad-market downside, not single-name risk.",
    dimensions: [
      { label: "Risk match", value: 8.4 },
      { label: "Risk-adj. return", value: 7.2 },
      { label: "Downside protection", value: 8.1 },
    ],
  },
  growth: {
    id: "growth",
    label: "High-growth portfolio",
    score: 541,
    band: "Watch",
    takeaway:
      "Looks diversified by ticker count, but the risk is concentrated high-beta growth — a tech-and-crypto selloff hits ~3× harder.",
    dimensions: [
      { label: "Risk match", value: 3.9 },
      { label: "Risk-adj. return", value: 6.1 },
      { label: "Downside protection", value: 2.8 },
    ],
  },
};

/** Resolve a `?book=` query param to a fixed book, defaulting safely. */
export function parseShareBook(raw: string | string[] | undefined): ShareBook {
  const v = Array.isArray(raw) ? raw[0] : raw;
  if (v === "balanced" || v === "growth") return SHARE_BOOKS[v];
  return SHARE_BOOKS[DEFAULT_SHARE_BOOK];
}

/** Canonical site origin for absolute share URLs (so links unfurl the prod page). */
export const SHARE_SITE_URL =
  process.env.NEXT_PUBLIC_SITE_URL || "https://mindmarket.app";

/** Absolute URL of the shareable card page for a given book. */
export function buildShareUrl(book: ShareBookId, origin: string = SHARE_SITE_URL): string {
  return `${origin.replace(/\/$/, "")}/share/risk-card?book=${book}`;
}

/** Short, no-advice social caption for the card. */
export function shareCaption(book: ShareBook): string {
  return `My ${book.label.toLowerCase()} scored ${book.score}/1000 (${book.band}) on MindMarket's free risk X-ray. What's yours?`;
}

/** X (Twitter) web-intent URL with pre-filled text + the card link. */
export function xIntentUrl(book: ShareBook, origin: string = SHARE_SITE_URL): string {
  const u = new URL("https://twitter.com/intent/tweet");
  u.searchParams.set("text", shareCaption(book));
  u.searchParams.set("url", buildShareUrl(book.id, origin));
  return u.toString();
}

/** LinkedIn share URL for the card link. */
export function linkedInIntentUrl(book: ShareBook, origin: string = SHARE_SITE_URL): string {
  const u = new URL("https://www.linkedin.com/sharing/share-offsite/");
  u.searchParams.set("url", buildShareUrl(book.id, origin));
  return u.toString();
}
