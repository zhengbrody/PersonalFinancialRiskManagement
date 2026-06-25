import { describe, it, expect } from "vitest";
import {
  SHARE_BOOKS,
  DEFAULT_SHARE_BOOK,
  parseShareBook,
  buildShareUrl,
  xIntentUrl,
  linkedInIntentUrl,
  shareCaption,
} from "./share-card";
import { scoreBand } from "@/components/score-gauge";
import { BALANCED, GROWTH } from "@/components/sample-cockpit";

describe("parseShareBook", () => {
  it("resolves a valid book id", () => {
    expect(parseShareBook("balanced").id).toBe("balanced");
    expect(parseShareBook("growth").id).toBe("growth");
  });
  it("defaults unknown / missing / forged input to the default book", () => {
    expect(parseShareBook(undefined).id).toBe(DEFAULT_SHARE_BOOK);
    expect(parseShareBook("9999").id).toBe(DEFAULT_SHARE_BOOK);
    expect(parseShareBook("../etc/passwd").id).toBe(DEFAULT_SHARE_BOOK);
  });
  it("takes the first value when given an array (Next repeated query param)", () => {
    expect(parseShareBook(["balanced", "growth"]).id).toBe("balanced");
  });
});

describe("SHARE_BOOKS band is derived from the score (no invented number)", () => {
  it("each book's band matches scoreBand(score)", () => {
    for (const book of Object.values(SHARE_BOOKS)) {
      expect(book.band).toBe(scoreBand(book.score).label);
    }
  });
});

describe("SHARE_BOOKS stays in sync with the demo cockpit (drift guard)", () => {
  it("scores and takeaways mirror the cockpit constants", () => {
    expect(SHARE_BOOKS.balanced.score).toBe(BALANCED.metrics.score);
    expect(SHARE_BOOKS.growth.score).toBe(GROWTH.metrics.score);
    // dimension values carry over verbatim
    expect(SHARE_BOOKS.balanced.dimensions).toEqual(BALANCED.metrics.dimensions);
    expect(SHARE_BOOKS.growth.dimensions).toEqual(GROWTH.metrics.dimensions);
  });
});

describe("share URLs", () => {
  it("buildShareUrl is absolute and carries the book", () => {
    expect(buildShareUrl("growth", "https://mindmarket.app")).toBe(
      "https://mindmarket.app/share/risk-card?book=growth",
    );
  });
  it("strips a trailing slash on the origin", () => {
    expect(buildShareUrl("balanced", "https://mindmarket.app/")).toBe(
      "https://mindmarket.app/share/risk-card?book=balanced",
    );
  });
  it("xIntentUrl includes the caption text and the card url", () => {
    const u = new URL(xIntentUrl(SHARE_BOOKS.growth, "https://mindmarket.app"));
    expect(u.hostname).toBe("twitter.com");
    expect(u.searchParams.get("url")).toBe(
      "https://mindmarket.app/share/risk-card?book=growth",
    );
    expect(u.searchParams.get("text")).toBe(shareCaption(SHARE_BOOKS.growth));
  });
  it("linkedInIntentUrl points at the card url", () => {
    const u = new URL(linkedInIntentUrl(SHARE_BOOKS.balanced, "https://mindmarket.app"));
    expect(u.hostname).toBe("www.linkedin.com");
    expect(u.searchParams.get("url")).toBe(
      "https://mindmarket.app/share/risk-card?book=balanced",
    );
  });
  it("caption carries no buy/sell advice", () => {
    const caption = shareCaption(SHARE_BOOKS.growth).toLowerCase();
    for (const word of ["buy", "sell", "should"]) expect(caption).not.toContain(word);
  });
});
