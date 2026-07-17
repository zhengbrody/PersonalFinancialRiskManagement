import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

type AuthState = { user: { id: string } | null; configured: boolean; loading: boolean };
const authMock = vi.fn((): AuthState => ({ user: null, configured: true, loading: false }));
vi.mock("@/lib/auth-context", () => ({ useAuth: () => authMock() }));

// Heavy live market components fetch on mount — stub to pure markers.
vi.mock("@/components/market-regime", () => ({ MarketRegime: () => <div data-testid="regime" /> }));
vi.mock("@/components/regime-context", () => ({
  RegimeContext: () => <div data-testid="ml-regime" />,
  RegimeContextLine: () => <div data-testid="ml-regime-line" />,
}));
vi.mock("@/components/market-season", () => ({ MarketSeason: () => <div data-testid="season" /> }));
vi.mock("@/components/market-movers", () => ({ MarketMovers: () => <div data-testid="movers" /> }));
vi.mock("@/components/market-news", () => ({ MarketNews: () => <div data-testid="news" /> }));
vi.mock("@/components/portfolio-sentiment", () => ({
  PortfolioSentiment: () => <div data-testid="sentiment" />,
}));
vi.mock("@/components/macro-snapshot", () => ({ MacroSnapshot: () => <div data-testid="macro" /> }));

import { MarketsGate } from "./markets-gate";

beforeEach(() => authMock.mockReturnValue({ user: null, configured: true, loading: false }));

describe("MarketsGate", () => {
  it("anonymous → marketing intro + live public preview + sign-in CTA (no app-only bits)", () => {
    render(<MarketsGate />);
    expect(screen.getByText(/See what is moving/i)).toBeInTheDocument();
    expect(screen.getByText(/What is moving right now/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Risk Today/i })).toHaveAttribute(
      "href",
      "/risk-today",
    );
    expect(
      screen
        .getAllByRole("link", { name: /create risk workspace/i })
        .some((link) => link.getAttribute("href") === "/signup"),
    ).toBe(true);
    expect(screen.getByTestId("regime")).toBeInTheDocument(); // live preview
    expect(screen.getByTestId("macro")).toBeInTheDocument();
    // The auth-only desk bits are NOT in the intro:
    expect(screen.queryByTestId("sentiment")).not.toBeInTheDocument();
  });

  it("signed-in → the full live desk (sentiment), not the intro", () => {
    authMock.mockReturnValue({ user: { id: "u1" }, configured: true, loading: false });
    render(<MarketsGate />);
    expect(screen.getByRole("heading", { name: "Markets", level: 1 })).toBeInTheDocument();
    expect(screen.getByTestId("sentiment")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /near-term model signal/i })).toHaveAttribute(
      "href",
      "/risk-today",
    );
    expect(screen.queryByText(/See what is moving/i)).not.toBeInTheDocument();
  });
});
