// NOTE: in production Caddy serves /robots.txt and /sitemap.xml from
// assets/seo/ (see Caddyfile), which SHADOWS these Next routes. Keep the
// two in sync when adding public pages — this file is what local dev and
// any non-Caddy deployment will serve.
import type { MetadataRoute } from "next";
import { LEARN_SLUGS } from "@/lib/learn-content";
import { LEGAL_DOCS } from "@/lib/legal-content";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://mindmarket.app";

const PUBLIC_ROUTES: Array<{
  path: string;
  changeFrequency: MetadataRoute.Sitemap[number]["changeFrequency"];
  priority: number;
}> = [
  { path: "/", changeFrequency: "weekly", priority: 1.0 },
  { path: "/demo-risk-check", changeFrequency: "weekly", priority: 0.95 },
  { path: "/score", changeFrequency: "weekly", priority: 0.85 },
  { path: "/product", changeFrequency: "monthly", priority: 0.9 },
  { path: "/learn", changeFrequency: "weekly", priority: 0.9 },
  { path: "/markets", changeFrequency: "daily", priority: 0.8 },
  { path: "/risk-today", changeFrequency: "daily", priority: 0.85 },
  { path: "/pricing", changeFrequency: "monthly", priority: 0.7 },
  { path: "/portfolio-risk-management", changeFrequency: "monthly", priority: 0.9 },
  { path: "/ai-portfolio-analysis", changeFrequency: "monthly", priority: 0.85 },
  { path: "/portfolio-var-stress-testing", changeFrequency: "monthly", priority: 0.85 },
  {
    path: "/personal-portfolio-risk-analysis",
    changeFrequency: "monthly",
    priority: 0.85,
  },
  { path: "/margin-risk-calculator", changeFrequency: "monthly", priority: 0.85 },
  { path: "/portfolio-stress-test", changeFrequency: "monthly", priority: 0.85 },
  {
    path: "/stock-portfolio-concentration-risk",
    changeFrequency: "monthly",
    priority: 0.8,
  },
  { path: "/robinhood-margin-risk", changeFrequency: "monthly", priority: 0.8 },
  { path: "/about", changeFrequency: "monthly", priority: 0.8 },
  { path: "/demo", changeFrequency: "monthly", priority: 0.8 },
  { path: "/sample-risk-report", changeFrequency: "monthly", priority: 0.8 },
  { path: "/resources", changeFrequency: "monthly", priority: 0.7 },
];

export default function sitemap(): MetadataRoute.Sitemap {
  const now = new Date();
  const learn: MetadataRoute.Sitemap = LEARN_SLUGS.map((slug) => ({
    url: `${SITE_URL}/learn/${slug}`,
    lastModified: now,
    changeFrequency: "monthly" as const,
    priority: 0.8,
  }));
  const legal: MetadataRoute.Sitemap = LEGAL_DOCS.map((d) => ({
    url: `${SITE_URL}/legal/${d.slug}`,
    lastModified: now,
    changeFrequency: "yearly" as const,
    priority: 0.3,
  }));
  return [
    ...PUBLIC_ROUTES.map((route) => ({
      url: `${SITE_URL}${route.path}`,
      lastModified: now,
      changeFrequency: route.changeFrequency,
      priority: route.priority,
    })),
    ...learn,
    ...legal,
  ];
}
