import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

const authMock = vi.fn(() => ({ user: null, configured: true, loading: false }));
vi.mock("@/lib/auth-context", () => ({ useAuth: () => authMock() }));

import ResourcesPage from "./page";
import { LEARN_TOPICS } from "@/lib/learn-content";

beforeEach(() => authMock.mockReturnValue({ user: null, configured: true, loading: false }));

function renderedHrefs(): Set<string> {
  render(<ResourcesPage />);
  return new Set(
    screen.getAllByRole("link").map((a) => a.getAttribute("href") ?? ""),
  );
}

describe("/resources hub", () => {
  it("links every learn guide (incl. the three new ones)", () => {
    const hrefs = renderedHrefs();
    for (const t of LEARN_TOPICS) {
      expect(hrefs.has(`/learn/${t.slug}`)).toBe(true);
    }
    expect(hrefs.has("/learn/sharpe-ratio-explained")).toBe(true);
    expect(hrefs.has("/learn/maximum-drawdown")).toBe(true);
    expect(hrefs.has("/learn/diversification-correlation")).toBe(true);
  });

  it("gives the previously-orphaned Caddy keyword pages an inbound link", () => {
    const hrefs = renderedHrefs();
    for (const href of [
      "/margin-risk-calculator",
      "/robinhood-margin-risk",
      "/portfolio-stress-test",
      "/stock-portfolio-concentration-risk",
    ]) {
      expect(hrefs.has(href)).toBe(true);
    }
  });
});
