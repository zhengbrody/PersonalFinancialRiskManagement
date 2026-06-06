import type { MetadataRoute } from "next";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://mindmarket.app";

const PUBLIC_ROUTES: Array<{
  path: string;
  changeFrequency: MetadataRoute.Sitemap[number]["changeFrequency"];
  priority: number;
}> = [
  { path: "/", changeFrequency: "weekly", priority: 1.0 },
  { path: "/score", changeFrequency: "weekly", priority: 0.85 },
  { path: "/markets", changeFrequency: "daily", priority: 0.8 },
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
];

export default function sitemap(): MetadataRoute.Sitemap {
  const now = new Date();
  return PUBLIC_ROUTES.map((route) => ({
    url: `${SITE_URL}${route.path}`,
    lastModified: now,
    changeFrequency: route.changeFrequency,
    priority: route.priority,
  }));
}
