import { describe, it, expect } from "vitest";
import { LEGAL_DOCS, LEGAL_BY_SLUG, LEGAL_SLUGS } from "./legal-content";

describe("legal-content integrity", () => {
  it("ships exactly terms / privacy / disclaimer with unique slugs", () => {
    expect(LEGAL_SLUGS).toEqual(["terms", "privacy", "disclaimer"]);
    expect(new Set(LEGAL_SLUGS).size).toBe(LEGAL_DOCS.length);
  });

  it("every doc has the required, non-empty fields", () => {
    for (const d of LEGAL_DOCS) {
      expect(d.title.length).toBeGreaterThan(0);
      expect(d.metaTitle).toMatch(/MindMarket/);
      expect(d.description.length).toBeGreaterThan(20);
      expect(d.lastUpdated).toMatch(/^\d{4}-\d{2}-\d{2}$/);
      expect(d.intro.length).toBeGreaterThan(20);
      expect(d.sections.length).toBeGreaterThan(0);
      expect(d.contactEmail).toContain("@");
    }
  });

  it("every section has a heading and well-formed blocks", () => {
    for (const d of LEGAL_DOCS) {
      for (const s of d.sections) {
        expect(s.heading.length).toBeGreaterThan(0);
        expect(s.blocks.length).toBeGreaterThan(0);
        for (const b of s.blocks) {
          if (b.kind === "list") expect(b.items.length).toBeGreaterThan(0);
          else if (b.kind === "lead") expect(b.label.length).toBeGreaterThan(0);
          else expect(b.text.length).toBeGreaterThan(0);
        }
      }
    }
  });

  it("indexes by slug", () => {
    expect(LEGAL_BY_SLUG.terms.title).toBe("Terms of Service");
    expect(LEGAL_BY_SLUG.privacy.title).toBe("Privacy Policy");
    expect(LEGAL_BY_SLUG.disclaimer.title).toBe("Financial Disclaimer");
    expect(LEGAL_BY_SLUG.nope).toBeUndefined();
  });
});
