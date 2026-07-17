import { describe, expect, it } from "vitest";
import robots from "./robots";
import sitemap from "./sitemap";
import { SEO_PAGES } from "@/lib/seo-content";
import { seoMetadata } from "@/components/marketing/seo-landing";

describe("SEO routes", () => {
  const urls = sitemap().map((entry) => entry.url);

  it("exposes public marketing routes in the sitemap", () => {
    expect(urls).toContain("https://mindmarket.app/");
    expect(urls).toContain("https://mindmarket.app/markets");
    expect(urls).toContain("https://mindmarket.app/product");
    expect(urls).toContain("https://mindmarket.app/risk-today");
    expect(urls).toContain("https://mindmarket.app/methodology/regime-model");
    expect(urls).toContain("https://mindmarket.app/about");
    expect(urls).not.toContain("https://mindmarket.app/score");
    expect(urls).not.toContain("https://mindmarket.app/pricing");
  });

  it("includes every migrated SEO landing page (canonical URLs preserved)", () => {
    for (const p of SEO_PAGES) {
      expect(urls).toContain(`https://mindmarket.app${p.path}`);
    }
  });

  it("keeps the canonical demo and drops the retired /demo (301) — no duplicate demo", () => {
    expect(urls).toContain("https://mindmarket.app/demo-risk-check");
    expect(urls).not.toContain("https://mindmarket.app/demo");
  });

  it("uses fixed lastmod dates, not build-time now", () => {
    // Every entry has a fixed YYYY-MM-DD string (no entry stamped to today's build).
    for (const e of sitemap()) {
      expect(typeof e.lastModified === "string").toBe(true);
      expect(String(e.lastModified)).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    }
  });

  it("each SEO page has a title, description, and self-referential canonical", () => {
    for (const p of SEO_PAGES) {
      const m = seoMetadata(p.path);
      expect((m.title as { absolute?: string })?.absolute).toBe(p.title);
      expect(m.description).toBe(p.description);
      expect((m.alternates as { canonical?: string })?.canonical).toBe(p.path);
      // OG siteName must be "MindMarket" (not "mindmarket.app").
      expect((m.openGraph as { siteName?: string })?.siteName).toBe("MindMarket");
    }
  });

  it("allows public routes and blocks private/account routes", () => {
    const config = robots();
    const rule = Array.isArray(config.rules) ? config.rules[0] : config.rules;
    expect(rule.allow).toContain("/");
    expect(rule.allow).toContain("/product");
    expect(rule.disallow).toContain("/login");
    expect(rule.disallow).toContain("/portfolios");
    expect(rule.disallow).toContain("/pricing");
    expect(rule.disallow).toContain("/research");
    expect(rule.disallow).toContain("/settings");
    expect(config.sitemap).toBe("https://mindmarket.app/sitemap.xml");
  });
});
