/**
 * PortfolioSentiment: signed-in, on-demand scoring → per-holding chips; quota
 * → "see plans" CTA. MarketNews: public headline list.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithQuery } from "@/test-utils";

vi.mock("@/lib/analytics", () => ({ track: vi.fn() }));
vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({
    user: { id: "u-1", email: "owner@mindmarket.test" },
    accessToken: "jwt-here",
    configured: true,
    loading: false,
  }),
}));

import { PortfolioSentiment } from "./portfolio-sentiment";
import { MarketNews } from "./market-news";

function mockJson(body: Record<string, unknown>, status = 200) {
  const withMeta = { ...body, meta: { request_id: "r" } };
  return new Response(JSON.stringify(withMeta), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("PortfolioSentiment", () => {
  it("scores holdings on click and renders chips", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      mockJson({
        data: {
          sentiments: [{ ticker: "NVDA", score: 78, label: "Bullish", narrative: "Momentum.", headline_count: 4 }],
          ai_generated: true,
        },
        error: null,
        meta: {},
      }),
    );

    const user = userEvent.setup();
    renderWithQuery(<PortfolioSentiment />);
    await user.click(screen.getByRole("button", { name: /score my holdings/i }));

    expect(await screen.findByText("NVDA")).toBeInTheDocument();
    expect(screen.getByText("Bullish")).toBeInTheDocument();
    expect(screen.getByText("Momentum.")).toBeInTheDocument();
  });

  it("shows a see-plans CTA when out of credits", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      mockJson(
        { data: null, error: { code: "quota_exceeded", message: "out of credits" }, meta: {} },
        429,
      ),
    );

    const user = userEvent.setup();
    renderWithQuery(<PortfolioSentiment />);
    await user.click(screen.getByRole("button", { name: /score my holdings/i }));

    expect(await screen.findByText(/out of AI credits/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /see plans/i })).toBeInTheDocument();
  });
});

describe("MarketNews", () => {
  it("renders public headlines", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      mockJson({
        data: { items: [{ source: "Reuters", title: "Fed holds rates", link: "http://x", published: "today" }] },
        error: null,
        meta: {},
      }),
    );
    renderWithQuery(<MarketNews />);
    expect(await screen.findByText("Fed holds rates")).toBeInTheDocument();
  });
});
