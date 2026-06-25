/**
 * Single source of truth for the marketing nav links — shared by the desktop
 * inline nav, the mobile hamburger overlay, and the footer (so they never
 * drift). Kept in its own module to avoid a marketing-shell ⇄ mobile-nav import
 * cycle.
 */
export const NAV_LINKS: [string, string][] = [
  ["Product", "/product"],
  ["Learn", "/learn"],
  ["Markets", "/markets"],
  ["Demo", "/demo-risk-check"],
];
