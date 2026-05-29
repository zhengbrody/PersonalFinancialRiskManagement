/**
 * /portfolios/new contract.
 *
 *   1. Redirect to /login when signed out.
 *   2. Submit → POST /api/v1/portfolios with the entered values.
 *   3. Successful create → redirect /portfolios.
 *   4. Envelope error → message surfaced inline.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithQuery } from "@/test-utils";

const replaceMock = vi.fn();
const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock, push: pushMock }),
}));

const useAuthMock = vi.fn();
vi.mock("@/lib/auth-context", () => ({
  useAuth: () => useAuthMock(),
}));

import NewPortfolioPage from "./page";

function authed() {
  useAuthMock.mockReturnValue({
    user: { id: "u-1", email: "owner@mindmarket.test" },
    accessToken: "jwt-here",
    loading: false,
    configured: true,
    signIn: vi.fn(),
    signUp: vi.fn(),
    signOut: vi.fn(),
  });
}

afterEach(() => {
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

describe("NewPortfolioPage", () => {
  it("redirects to /login when signed out", () => {
    useAuthMock.mockReturnValue({
      user: null,
      accessToken: null,
      loading: false,
      configured: true,
      signIn: vi.fn(),
      signUp: vi.fn(),
      signOut: vi.fn(),
    });
    renderWithQuery(<NewPortfolioPage />);
    expect(replaceMock).toHaveBeenCalledWith("/login");
  });

  it("posts to /api/v1/portfolios with the form values + bearer token", async () => {
    authed();
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          data: {
            id: "p-new",
            user_id: "u-1",
            name: "Beta",
            holdings: { SPY: { shares: 10 } },
            margin_loan: 0,
            contributed_capital: 0,
            cash_balance: 0,
            is_default: false,
            created_at: null,
            updated_at: null,
          },
          error: null,
          meta: { request_id: "r" },
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    const user = userEvent.setup();
    renderWithQuery(<NewPortfolioPage />);

    await user.type(screen.getByLabelText(/portfolio name/i), "Beta");
    // Use the first prefilled SPY row for shares; clear avg_cost.
    await user.clear(screen.getByLabelText("Ticker 1"));
    await user.type(screen.getByLabelText("Ticker 1"), "SPY");
    await user.type(screen.getByLabelText("Shares 1"), "10");

    await user.click(
      screen.getByRole("button", { name: /create portfolio/i }),
    );

    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(1));
    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(String(url)).toMatch(/\/api\/v1\/portfolios$/);
    expect(init.method).toBe("POST");
    const body = JSON.parse(init.body as string);
    expect(body.name).toBe("Beta");
    expect(body.holdings.SPY).toEqual({ shares: 10 });
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer jwt-here");

    await waitFor(() =>
      expect(replaceMock).toHaveBeenCalledWith("/portfolios"),
    );
  });

  it("surfaces an envelope error inline without redirect", async () => {
    authed();
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          data: null,
          error: { code: "portfolio_create_failed", message: "RLS blocked." },
          meta: { request_id: "r" },
        }),
        { status: 422, headers: { "Content-Type": "application/json" } },
      ),
    );

    const user = userEvent.setup();
    renderWithQuery(<NewPortfolioPage />);
    await user.type(screen.getByLabelText(/portfolio name/i), "X");
    await user.clear(screen.getByLabelText("Ticker 1"));
    await user.type(screen.getByLabelText("Ticker 1"), "SPY");
    await user.type(screen.getByLabelText("Shares 1"), "5");
    await user.click(
      screen.getByRole("button", { name: /create portfolio/i }),
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/rls blocked/i);
    expect(replaceMock).not.toHaveBeenCalled();
  });
});
