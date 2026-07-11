// Single sitemap source (Next). The old static assets/seo/sitemap.xml + the
// Caddy handle that served it are removed, so this is what production serves.
//
// `lastModified` is a FIXED content date per route, NOT `new Date()` — a build
// must not stamp every URL as "changed today". Bump a route's date when its
// content actually changes. Canonical URLs only: /demo is a 301 → /demo-risk-check
// and is intentionally absent.
import type { MetadataRoute } from "next";
import { SEO_PAGES } from "@/lib/seo-content";
import { LEARN_SLUGS } from "@/lib/learn-content";
import { LEGAL_DOCS } from "@/lib/legal-content";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://mindmarket.app";

type Freq = MetadataRoute.Sitemap[number]["changeFrequency"];

// Non-SEO-landing Next routes (the 9 SEO landing pages come from SEO_PAGES).
const NEXT_ROUTES: { path: string; changeFrequency: Freq; priority: number; lastmod: string }[] = [
  { path: "/", changeFrequency: "weekly", priority: 1.0, lastmod: "2026-06-25" },
  { path: "/demo-risk-check", changeFrequency: "weekly", priority: 0.95, lastmod: "2026-06-25" },
  { path: "/score", changeFrequency: "weekly", priority: 0.85, lastmod: "2026-06-17" },
  { path: "/markets", changeFrequency: "daily", priority: 0.8, lastmod: "2026-06-17" },
  { path: "/risk-today", changeFrequency: "daily", priority: 0.85, lastmod: "2026-07-11" },
  { path: "/pricing", changeFrequency: "monthly", priority: 0.7, lastmod: "2026-06-17" },
  { path: "/product", changeFrequency: "monthly", priority: 0.9, lastmod: "2026-06-17" },
  { path: "/learn", changeFrequency: "weekly", priority: 0.9, lastmod: "2026-06-25" },
  { path: "/resources", changeFrequency: "monthly", priority: 0.7, lastmod: "2026-06-25" },
  { path: "/about", changeFrequency: "monthly", priority: 0.8, lastmod: "2026-07-11" },
  { path: "/methodology/health-score", changeFrequency: "monthly", priority: 0.75, lastmod: "2026-07-10" },
  { path: "/methodology/regime-model", changeFrequency: "monthly", priority: 0.7, lastmod: "2026-07-11" },
];

// The three learn topics added later carry a newer content date.
const LEARN_NEWER = new Set([
  "sharpe-ratio-explained",
  "maximum-drawdown",
  "diversification-correlation",
]);

export default function sitemap(): MetadataRoute.Sitemap {
  const rows: MetadataRoute.Sitemap = [];

  for (const r of NEXT_ROUTES) {
    rows.push({
      url: `${SITE_URL}${r.path}`,
      lastModified: r.lastmod,
      changeFrequency: r.changeFrequency,
      priority: r.priority,
    });
  }
  for (const p of SEO_PAGES) {
    rows.push({
      url: `${SITE_URL}${p.path}`,
      lastModified: p.lastmod,
      changeFrequency: p.changeFrequency,
      priority: p.priority,
    });
  }
  for (const slug of LEARN_SLUGS) {
    rows.push({
      url: `${SITE_URL}/learn/${slug}`,
      lastModified: LEARN_NEWER.has(slug) ? "2026-06-24" : "2026-06-17",
      changeFrequency: "monthly",
      priority: 0.85,
    });
  }
  for (const d of LEGAL_DOCS) {
    rows.push({
      url: `${SITE_URL}/legal/${d.slug}`,
      lastModified: "2026-06-24",
      changeFrequency: "yearly",
      priority: 0.3,
    });
  }
  return rows;
}
