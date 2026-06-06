import { describe, expect, it } from "vitest";
import robots from "./robots";
import sitemap from "./sitemap";

describe("SEO routes", () => {
  it("exposes public marketing routes in the sitemap", () => {
    const urls = sitemap().map((entry) => entry.url);
    expect(urls).toContain("https://mindmarket.app/");
    expect(urls).toContain("https://mindmarket.app/score");
    expect(urls).toContain("https://mindmarket.app/markets");
    expect(urls).toContain("https://mindmarket.app/pricing");
  });

  it("allows public routes and blocks private/account routes", () => {
    const config = robots();
    const rule = Array.isArray(config.rules) ? config.rules[0] : config.rules;
    expect(rule.allow).toContain("/");
    expect(rule.allow).toContain("/score");
    expect(rule.disallow).toContain("/login");
    expect(rule.disallow).toContain("/portfolios");
    expect(rule.disallow).toContain("/research");
    expect(rule.disallow).toContain("/settings");
    expect(config.sitemap).toBe("https://mindmarket.app/sitemap.xml");
  });
});
