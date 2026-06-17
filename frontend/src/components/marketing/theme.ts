/**
 * Shared marketing design tokens — the premium, always-dark "Citadel ×
 * Robinhood" palette used by every pre-login surface (landing + /product +
 * /learn + /demo-risk-check + auth pages). These are intentional MARKETING
 * LITERALS, distinct from the app's `.dark` theme tokens (globals.css), so the
 * pre-login experience renders identically regardless of the market-hours
 * theme. Centralised here so the look is changed in ONE place.
 */

import { type CSSProperties } from "react";

export const C = {
  ink: "#07090C",
  panel: "#10161D",
  paper: "#F8FAFC",
  slate: "#AAB4C2",
  slateDim: "rgba(170,180,194,.72)",
  teal: "#2FA7BC",
  tealDeep: "#0B7285",
  gold: "#E0AE2A",
  up: "#38D39F",
  down: "#FF6B6B",
  hair: "rgba(255,255,255,0.09)",
  hairStrong: "rgba(255,255,255,0.16)",
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
