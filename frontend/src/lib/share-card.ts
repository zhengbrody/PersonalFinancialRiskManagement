/**
 * Shareable risk cards — the single source of truth for the public page and OG route.
 *
 * Framework-free + pure (no React, no client imports) so the server OG route can
 * import it safely. The card's SCORE comes from a constant keyed by `book`,
 * NEVER from the query string — a hand-edited `?score=9999` cannot forge a fake
 * number on this public, un-authed, cache-poisonable surface. That keeps the
 * product-wide "never invent a number" invariant on the shareable artifact.
 *
 * Real portfolios use a backend-signed, coarse-band token; the token never
 * contains identity, positions, tickers, exact scores or dollar values.
 * SHARE_BOOKS mirrors the BALANCED/GROWTH demo books in
 * components/sample-cockpit.tsx; share-card.test.ts asserts they stay in sync
 * (score + band) so they can't silently drift.
 */

// Type-only import (erased at build — no runtime/client code pulled in, so the
// server OG route can still import this module safely).
import type { ScoreBand } from "@/components/score-gauge";
import { z } from "zod";

export type ShareBookId = "balanced" | "growth";
// Reuse the canonical 0–1000 band union from the score gauge (type-only import,
// erased at build) so the two can't drift.
export type ShareBand = ScoreBand;

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
const SHARE_SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://mindmarket.app";

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

export const realShareCardSchema = z.strictObject({
  card: z.strictObject({
    v: z.literal(1),
    score_band: z.enum(["poor", "watch", "healthy", "strong"]),
    risk_fit: z.enum(["above", "aligned", "below", "unavailable", "not_confirmed"]),
    top_risk_category: z.enum([
      "data_quality", "concentration", "leverage", "options", "downside",
      "volatility", "market_sensitivity", "overall_balance",
    ]),
    stress_band: z.enum([
      "under_5_pct", "5_to_10_pct", "10_to_20_pct", "over_20_pct", "unavailable",
    ]),
    confidence_label: z.enum(["high", "medium", "low"]),
    as_of: z.string(),
    model_version: z.string(),
    exp: z.number().int(),
  }),
});

export type RealShareCard = z.infer<typeof realShareCardSchema>["card"];

export function buildTokenShareUrl(token: string, origin: string = SHARE_SITE_URL): string {
  return `${origin.replace(/\/$/, "")}/share/risk-card?token=${encodeURIComponent(token)}`;
}

export function tokenXIntentUrl(card: RealShareCard, token: string): string {
  const u = new URL("https://twitter.com/intent/tweet");
  u.searchParams.set(
    "text",
    `My portfolio risk profile is ${titleCase(card.score_band)} on MindMarket — shared without positions or exact values.`,
  );
  u.searchParams.set("url", buildTokenShareUrl(token));
  return u.toString();
}

export function tokenLinkedInIntentUrl(token: string): string {
  const u = new URL("https://www.linkedin.com/sharing/share-offsite/");
  u.searchParams.set("url", buildTokenShareUrl(token));
  return u.toString();
}

export function titleCase(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function riskFitLabel(value: RealShareCard["risk_fit"]): string {
  return value === "not_confirmed" ? "Preference not confirmed" : titleCase(value);
}

export function stressBandLabel(value: RealShareCard["stress_band"]): string {
  return {
    under_5_pct: "Under 5% impact",
    "5_to_10_pct": "5–10% impact",
    "10_to_20_pct": "10–20% impact",
    over_20_pct: "Over 20% impact",
    unavailable: "Unavailable",
  }[value];
}
