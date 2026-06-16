/**
 * Learn content integrity: unique slugs, complete topics, valid cross-links —
 * so /learn/[slug] pages + sitemap never reference a missing topic.
 */

import { describe, expect, it } from "vitest";
import { LEARN_BY_SLUG, LEARN_SLUGS, LEARN_TOPICS } from "./learn-content";

describe("learn-content", () => {
  it("has the seven brief topics with unique slugs", () => {
    expect(LEARN_SLUGS).toEqual(Array.from(new Set(LEARN_SLUGS))); // unique
    for (const slug of [
      "portfolio-risk-management",
      "var-cvar-explained",
      "factor-exposure",
      "stress-testing",
      "margin-risk",
      "options-risk",
      "stock-research",
    ]) {
      expect(LEARN_BY_SLUG[slug]).toBeTruthy();
    }
  });

  it("every topic is complete (title, meta, sections, faqs)", () => {
    for (const t of LEARN_TOPICS) {
      expect(t.metaTitle.length).toBeGreaterThan(10);
      expect(t.description.length).toBeGreaterThan(20);
      expect(t.sections.length).toBeGreaterThanOrEqual(2);
      expect(t.faqs.length).toBeGreaterThanOrEqual(2);
      t.sections.forEach((s) => expect(s.paragraphs.length).toBeGreaterThan(0));
    }
  });

  it("every related link points to an existing topic", () => {
    for (const t of LEARN_TOPICS) {
      for (const slug of t.related) {
        expect(LEARN_BY_SLUG[slug], `${t.slug} → ${slug}`).toBeTruthy();
      }
    }
  });

  it("contains no buy/sell advice language", () => {
    const corpus = JSON.stringify(LEARN_TOPICS).toLowerCase();
    expect(corpus).not.toMatch(/\bbuy this\b|\bsell this\b|\bbuy now\b|guaranteed return/);
  });
});
