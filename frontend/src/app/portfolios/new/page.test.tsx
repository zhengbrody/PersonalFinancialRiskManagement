/**
 * /portfolios/new contract.
 *
 *   1. Redirect to /login when signed out.
 *   2. Submit → POST /api/v1/portfolios with the entered values.
 *   3. Post-create navigation is driven by the create RESPONSE, not the form:
 *        - is_default:true  (first/only book, or explicit default) → /score
 *        - is_default:false (existing user's extra book)           → /portfolios
 *      so a second non-default book never lands on the OLD default's score.
 *   4. Cancel is context-aware: onboarding (0 portfolios) → /, existing → /portfolios.
 *   5. Envelope error → message surfaced inline (no redirect).
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

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

/**
 * Render with a fresh client whose `portfolios/me` cache is PRE-SEEDED, so the
 * user's existing-portfolio count is deterministic on first render (no async
 * race) — that's what the context-aware Cancel reads. staleTime:Infinity keeps
 * the seeded value fresh so it isn't refetched out from under the test.
 */
function renderNew(existing: unknown[] = []) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: Infinity },
      mutations: { retry: false },
    },
  });
  // key = ["portfolios","me", user.id] — see useMyPortfolios()
  client.setQueryData(["portfolios", "me", "u-1"], { portfolios: existing } as never);
  return render(<NewPortfolioPage />, {
    wrapper: ({ children }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  });
}

afterEach(() => {
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** Route by URL: the form fetches /market/prices for the implied-P&L hint, and
 * the page reads /portfolios/me for the Cancel target — answer both, and only
 * let the POST to /api/v1/portfolios consume the create mock. */
function routeFetch(create: { body: unknown; status?: number }, existing: unknown[] = []) {
  return vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/market/prices"))
      return Promise.resolve(json({ data: { prices: [], requested: [] }, error: null, meta: { request_id: "p" } }));
    if (url.includes("/api/v1/portfolios/me"))
      return Promise.resolve(json({ data: { portfolios: existing }, error: null, meta: { request_id: "m" } }));
    if (url.match(/\/api\/v1\/portfolios$/))
      return Promise.resolve(json(create.body, create.status ?? 200));
    return Promise.resolve(json({ data: {}, error: null, meta: { request_id: "x" } }));
  });
}

/** A create-endpoint envelope for a PortfolioRow with the given default flag. */
function createdRow(is_default: boolean, name = "Beta") {
  return {
    data: {
      id: "p-new",
      user_id: "u-1",
      name,
      holdings: { SPY: { shares: 10 } },
      margin_loan: 0,
      contributed_capital: 0,
      cash_balance: 0,
      is_default,
      created_at: null,
      updated_at: null,
    },
    error: null,
    meta: { request_id: "r" },
  };
}

async function fillAndSubmit(user: ReturnType<typeof userEvent.setup>, name = "Beta") {
  await user.type(screen.getByLabelText(/portfolio name/i), name);
  await user.clear(screen.getByLabelText("Ticker 1"));
  await user.type(screen.getByLabelText("Ticker 1"), "SPY");
  await user.type(screen.getByLabelText("Shares 1"), "10");
  await user.click(screen.getByRole("button", { name: /create portfolio/i }));
}

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
    renderNew();
    expect(replaceMock).toHaveBeenCalledWith("/login");
  });

  it("posts to /api/v1/portfolios with the form values + bearer token", async () => {
    authed();
    const fetchSpy = routeFetch({ body: createdRow(false) });
    const user = userEvent.setup();
    renderNew();
    await fillAndSubmit(user);

    const createCall = await waitFor(() => {
      const c = fetchSpy.mock.calls.find(
        (call) => String(call[0]).match(/\/api\/v1\/portfolios$/) && (call[1] as RequestInit)?.method === "POST",
      );
      expect(c).toBeDefined();
      return c!;
    });
    const init = createCall[1] as RequestInit;
    expect(init.method).toBe("POST");
    const body = JSON.parse(init.body as string);
    expect(body.name).toBe("Beta");
    expect(body.holdings.SPY).toEqual({ shares: 10 });
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer jwt-here");
  });

  it("first portfolio (auto-promoted to default) → /score", async () => {
    authed();
    // Backend auto-promotes a user's first portfolio → the response is default.
    routeFetch({ body: createdRow(true) }, []);
    const user = userEvent.setup();
    renderNew([]); // no existing portfolios
    await fillAndSubmit(user);
    await waitFor(() => expect(replaceMock).toHaveBeenCalledWith("/score"));
  });

  it("second non-default portfolio → /portfolios, never the previous default's score", async () => {
    authed();
    routeFetch({ body: createdRow(false) }, [{ id: "p-old" }]);
    const user = userEvent.setup();
    renderNew([{ id: "p-old" }]); // user already has a (default) portfolio
    await fillAndSubmit(user);
    await waitFor(() => expect(replaceMock).toHaveBeenCalledWith("/portfolios"));
    expect(replaceMock).not.toHaveBeenCalledWith("/score");
  });

  it("portfolio created explicitly as default → /score", async () => {
    authed();
    routeFetch({ body: createdRow(true) }, [{ id: "p-old" }]);
    const user = userEvent.setup();
    renderNew([{ id: "p-old" }]);
    await fillAndSubmit(user);
    await waitFor(() => expect(replaceMock).toHaveBeenCalledWith("/score"));
    expect(replaceMock).not.toHaveBeenCalledWith("/portfolios");
  });

  it("Cancel: onboarding user (0 portfolios) → /", async () => {
    authed();
    routeFetch({ body: createdRow(false) }, []);
    const user = userEvent.setup();
    renderNew([]); // no portfolios yet
    await user.click(screen.getByRole("button", { name: /cancel/i }));
    expect(pushMock).toHaveBeenCalledWith("/");
    expect(pushMock).not.toHaveBeenCalledWith("/portfolios");
  });

  it("Cancel: existing user (≥1 portfolio) → /portfolios", async () => {
    authed();
    routeFetch({ body: createdRow(false) }, [{ id: "p-old" }]);
    const user = userEvent.setup();
    renderNew([{ id: "p-old" }]); // already has a portfolio
    await user.click(screen.getByRole("button", { name: /cancel/i }));
    expect(pushMock).toHaveBeenCalledWith("/portfolios");
    expect(pushMock).not.toHaveBeenCalledWith("/");
  });

  it("surfaces an envelope error inline without redirect", async () => {
    authed();
    routeFetch({
      body: {
        data: null,
        error: { code: "portfolio_create_failed", message: "RLS blocked." },
        meta: { request_id: "r" },
      },
      status: 422,
    });
    const user = userEvent.setup();
    renderNew();
    await fillAndSubmit(user, "X");

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/rls blocked/i);
    expect(replaceMock).not.toHaveBeenCalled();
  });
});
