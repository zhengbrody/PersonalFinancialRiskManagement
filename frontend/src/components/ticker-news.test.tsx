/**
 * TickerNews: renders unified news items (type + source label) + source badges
 * from /research/news. Always shows the SEC filing entry (fail-soft).
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithQuery } from "@/test-utils";

vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({ user: { id: "u-1" }, accessToken: "jwt", configured: true, loading: false }),
}));

import { TickerNews } from "./ticker-news";

function newsJson() {
  return new Response(
    JSON.stringify({
      data: {
        items: [
          { title: "Apple beats earnings", url: "https://x/a", type: "news", source: "fmp", source_label: "FMP", site: "Reuters", published: "2026-06-13" },
          { title: "AAPL — SEC filings (EDGAR)", url: "https://sec/x", type: "filing", source: "sec", source_label: "SEC EDGAR", site: "SEC EDGAR", published: null },
        ],
        sources: [
          { field: "news", provider: "fmp", label: "FMP", role: "primary" },
          { field: "filings", provider: "sec", label: "SEC EDGAR", role: "primary" },
        ],
        warnings: [],
      },
      error: null,
      meta: { request_id: "r" },
    }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
}

afterEach(() => vi.restoreAllMocks());

describe("TickerNews", () => {
  it("renders nothing without a ticker", () => {
    const { container } = renderWithQuery(<TickerNews ticker={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders source-labeled items + source badges", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(newsJson());
    renderWithQuery(<TickerNews ticker="AAPL" />);
    expect(await screen.findByText("Apple beats earnings")).toBeInTheDocument();
    expect(screen.getByText(/AAPL — SEC filings/)).toBeInTheDocument();
    // source labels surface on rows + the header badge row
    expect(screen.getAllByText("FMP").length).toBeGreaterThan(0);
    expect(screen.getAllByText("SEC EDGAR").length).toBeGreaterThan(0);
  });
});
