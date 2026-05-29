/**
 * `/portfolios` page state-machine.
 *
 * Branches asserted:
 *   1. Anonymous (auth loaded, no user) → redirected to /login.
 *   2. Authed + envelope OK + empty list → empty-state CTA visible.
 *   3. Authed + envelope OK + 1 row → portfolio card with name + tickers.
 *   4. Authed + envelope error → destructive panel with API code.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithQuery } from "@/test-utils";

const replaceMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock, push: vi.fn() }),
}));

const useAuthMock = vi.fn();
vi.mock("@/lib/auth-context", () => ({
  useAuth: () => useAuthMock(),
}));

import PortfoliosPage from "./page";

function authed() {
  useAuthMock.mockReturnValue({
    user: { id: "u-1", email: "owner@mindmarket.test" },
    accessToken: "test-jwt",
    loading: false,
    configured: true,
    signIn: vi.fn(),
    signOut: vi.fn(),
  });
}

function mockEnvelope(body: unknown, init: { status?: number } = {}) {
  return vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
    new Response(JSON.stringify(body), {
      status: init.status ?? 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

afterEach(() => {
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

describe("PortfoliosPage", () => {
  it("redirects to /login when signed out", () => {
    useAuthMock.mockReturnValue({
      user: null,
      accessToken: null,
      loading: false,
      configured: true,
      signIn: vi.fn(),
      signOut: vi.fn(),
    });

    renderWithQuery(<PortfoliosPage />);
    expect(replaceMock).toHaveBeenCalledWith("/login");
  });

  it("renders the empty-state CTA when the user has no portfolios", async () => {
    authed();
    mockEnvelope({
      data: { user_id: "u-1", email: "owner@mindmarket.test", portfolios: [] },
      error: null,
      meta: { request_id: "r-1" },
    });

    renderWithQuery(<PortfoliosPage />);
    expect(
      await screen.findByText(/no portfolios yet/i),
    ).toBeInTheDocument();
  });

  it("renders a portfolio card on a successful response", async () => {
    authed();
    mockEnvelope({
      data: {
        user_id: "u-1",
        email: "owner@mindmarket.test",
        portfolios: [
          {
            id: "p-1",
            user_id: "u-1",
            name: "Default",
            holdings: { SPY: { shares: 100 }, BND: { shares: 50 } },
            margin_loan: 0,
            contributed_capital: 40000,
            cash_balance: 1000,
            is_default: true,
            created_at: null,
            updated_at: null,
          },
        ],
      },
      error: null,
      meta: { request_id: "r-2" },
    });

    renderWithQuery(<PortfoliosPage />);
    // Card title: matches once (exact-case). The lowercase "default"
    // badge has its own selector below.
    expect(await screen.findByText("Default")).toBeInTheDocument();
    expect(screen.getByText(/SPY, BND/)).toBeInTheDocument();
    // Two matches expected: card title + badge. Specifically assert both.
    expect(screen.getAllByText(/default/i)).toHaveLength(2);
  });

  it("renders the error panel when the envelope returns an error", async () => {
    authed();
    mockEnvelope(
      {
        data: null,
        error: { code: "server_error", message: "Could not load portfolios." },
        meta: { request_id: "r-3" },
      },
      { status: 500 },
    );

    renderWithQuery(<PortfoliosPage />);
    // Card title "Could not load portfolios" + body "Could not load
    // portfolios." both match; assert via findAllByText so the wait
    // resolves once the panel mounts, then assert count.
    const matches = await screen.findAllByText(/could not load portfolios/i);
    expect(matches.length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText(/server_error/i)).toBeInTheDocument();
  });
});
