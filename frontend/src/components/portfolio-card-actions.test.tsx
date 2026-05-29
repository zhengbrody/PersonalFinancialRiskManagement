/**
 * Delete button + confirm flow on the /portfolios card.
 *
 *   1. Initial: Edit + Delete buttons visible, no confirm panel.
 *   2. Click Delete → confirm panel; original buttons hidden.
 *   3. Click Cancel → back to initial state, no DELETE issued.
 *   4. Click Delete forever → DELETE /api/v1/portfolios/<id>; row vanishes
 *      from the cache (handled by mutation onSuccess invalidate).
 *
 * The card lives inside the /portfolios page; we test the page so the
 * mutation hook gets a real QueryClient via the test-utils wrapper.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithQuery } from "@/test-utils";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: pushMock }),
}));

const useAuthMock = vi.fn(() => ({
  user: { id: "u-1", email: "owner@mindmarket.test" },
  accessToken: "jwt-here",
  loading: false,
  configured: true,
  signIn: vi.fn(),
  signUp: vi.fn(),
  signOut: vi.fn(),
}));
vi.mock("@/lib/auth-context", () => ({
  useAuth: () => useAuthMock(),
}));

import PortfoliosPage from "@/app/portfolios/page";

function mockJson(body: unknown, init: { status?: number } = {}) {
  return new Response(JSON.stringify(body), {
    status: init.status ?? 200,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

const SAMPLE_LIST = {
  data: {
    user_id: "u-1",
    email: "owner@mindmarket.test",
    portfolios: [
      {
        id: "p-1",
        user_id: "u-1",
        name: "Sample",
        holdings: { SPY: { shares: 100 } },
        margin_loan: 0,
        contributed_capital: 0,
        cash_balance: 0,
        is_default: false,
        created_at: null,
        updated_at: null,
      },
    ],
  },
  error: null,
  meta: { request_id: "r" },
};

describe("PortfolioCard actions", () => {
  it("renders Edit + Delete buttons by default", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(mockJson(SAMPLE_LIST));
    renderWithQuery(<PortfoliosPage />);
    expect(await screen.findByRole("button", { name: /^edit$/i }))
      .toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^delete sample$/i }))
      .toBeInTheDocument();
    expect(screen.queryByText(/delete forever/i)).not.toBeInTheDocument();
  });

  it("Edit pushes to /portfolios/:id/edit", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(mockJson(SAMPLE_LIST));
    const user = userEvent.setup();
    renderWithQuery(<PortfoliosPage />);
    await user.click(await screen.findByRole("button", { name: /^edit$/i }));
    expect(pushMock).toHaveBeenCalledWith("/portfolios/p-1/edit");
  });

  it("Delete → Cancel returns to initial state without DELETE", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(mockJson(SAMPLE_LIST));
    const user = userEvent.setup();
    renderWithQuery(<PortfoliosPage />);

    await user.click(
      await screen.findByRole("button", { name: /^delete sample$/i }),
    );
    expect(await screen.findByText(/delete forever/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /cancel/i }));
    expect(screen.queryByText(/delete forever/i)).not.toBeInTheDocument();
    expect(fetchSpy).toHaveBeenCalledTimes(1); // only the initial list fetch
  });

  it("Delete → confirm issues DELETE with the bearer token", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      // first call: list
      .mockResolvedValueOnce(mockJson(SAMPLE_LIST))
      // second call: DELETE
      .mockResolvedValueOnce(
        mockJson({
          data: { deleted: true, id: "p-1" },
          error: null,
          meta: { request_id: "r" },
        }),
      )
      // third: refetch after invalidate
      .mockResolvedValueOnce(
        mockJson({
          data: { user_id: "u-1", email: "owner@mindmarket.test", portfolios: [] },
          error: null,
          meta: { request_id: "r" },
        }),
      );
    const user = userEvent.setup();
    renderWithQuery(<PortfoliosPage />);

    await user.click(
      await screen.findByRole("button", { name: /^delete sample$/i }),
    );
    await user.click(screen.getByRole("button", { name: /delete forever/i }));

    await waitFor(() => {
      const deleteCall = fetchSpy.mock.calls.find(
        (c) => (c[1] as RequestInit)?.method === "DELETE",
      );
      expect(deleteCall).toBeDefined();
      const [url, init] = deleteCall as [string, RequestInit];
      expect(String(url)).toMatch(/\/api\/v1\/portfolios\/p-1$/);
      const headers = init.headers as Record<string, string>;
      expect(headers.Authorization).toBe("Bearer jwt-here");
    });
  });
});
