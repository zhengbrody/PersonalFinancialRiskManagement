/**
 * Shared marketing design tokens — the premium, always-dark "Citadel ×
 * Robinhood" palette used by every pre-login surface (landing + /product +
 * /learn + /demo-risk-check + auth pages). These are intentional MARKETING
 * LITERALS, distinct from the app's `.dark` theme tokens (globals.css), so the
 * pre-login experience renders identically regardless of the market-hours
 * theme. Centralised here so the look is changed in ONE place.
 */

import { type CSSProperties } from "react";

// Marketing palette — MARKET-SYNCED. Each token is a CSS var (--mm-*) defined
// light + dark in globals.css, so every pre-login surface flips with the same
// `.dark` the app uses (light during the trading day, dark overnight). Dark =
// the canonical brand-mark palette (tokens/colors.css); light = a paper variant.
// Names are kept (ink/paper/…) for call-site stability; semantically `ink` is the
// page background and `paper` is the primary text — both flip with the theme.
export const C = {
  ink: "var(--mm-bg)", // page background
  panel: "var(--mm-panel)", // raised panel / gradient companion
  paper: "var(--mm-text)", // primary text
  slate: "var(--mm-text-dim)", // secondary text
  slateDim: "var(--mm-text-faint)",
  teal: "var(--mm-teal)", // accent (text/links)
  tealDeep: "var(--mm-teal-deep)", // the "M" disc
  gold: "var(--mm-gold)", // signal accent
  up: "var(--mm-up)",
  down: "var(--mm-down)",
  hair: "var(--mm-hairline)", // hairline border
  hairStrong: "var(--mm-hairline-strong)",
  // Surfaces / effects that must invert between light & dark:
  cardGrad: "var(--mm-card-grad)", // hairline card fill
  navBg: "var(--mm-nav-bg)", // scrolled fixed-nav backdrop
  chipBg: "var(--mm-chip-bg)", // floating stat chip
  glowTeal: "var(--mm-glow-teal)", // hero radial glow
  glowGold: "var(--mm-glow-gold)",
  statGrad: "var(--mm-stat-grad)", // big gradient numerals
  ctaBg: "var(--mm-cta-bg)", // primary button (inverts: dark btn on light)
  ctaFg: "var(--mm-cta-fg)",
  track: "var(--mm-track)", // bar/progress track
  surfaceFaint: "var(--mm-surface-faint)", // faint inset surface
} as const;

/** Instrument Serif (wired in layout.tsx as --font-display) for headlines. */
export const display: CSSProperties = { fontFamily: "var(--font-display, Georgia, serif)" };
/** Geist Mono, tabular — for figures. */
export const mono: CSSProperties = {
  fontFamily: "var(--font-geist-mono, ui-monospace, monospace)",
  fontVariantNumeric: "tabular-nums",
};

export const eyebrow: CSSProperties = {
  fontSize: 12,
  fontWeight: 500,
  textTransform: "uppercase",
  letterSpacing: ".18em",
  color: C.teal,
  margin: "0 0 14px",
};

export const secTitle: CSSProperties = {
  ...display,
  fontWeight: 400,
  fontSize: "clamp(30px,3.6vw,46px)",
  lineHeight: 1.08,
  letterSpacing: "-0.01em",
  margin: 0,
};

/** Body prose on the dark marketing surface. */
export const bodyText: CSSProperties = {
  color: C.slate,
  fontSize: 16,
  lineHeight: 1.65,
  margin: 0,
};
