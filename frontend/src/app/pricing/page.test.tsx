/**
 * /pricing page contract.
 *
 *   1. Anonymous: shows plans but Subscribe → /signup.
 *   2. Authed Free: Subscribe → POST /checkout_session → window.location
 *      is set to the returned Stripe URL (verified via spy).
 *   3. Authed Basic: the "Basic" card is marked Current and disabled.
 *   4. Stripe error → friendly message rendered.
 *   5. ?checkout=cancelled query → cancellation banner shown.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithQuery } from "@/test-utils";

const pushMock = vi.fn();
const searchMock = vi.fn(() => ({ get: () => null }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock, replace: vi.fn() }),
  useSearchParams: () => searchMock(),
}));

const useAuthMock = vi.fn();
vi.mock("@/lib/auth-context", () => ({
  useAuth: () => useAuthMock(),
}));

import PricingPage from "./page";

function mockJson(body: unknown, init: { status?: number } = {}) {
  return new Response(JSON.stringify(body), {
    status: init.status ?? 200,
    headers: { "Content-Type": "application/json" },
  });
}

const BILLING_FREE = {
  data: {
    user_id: "u-1",
    email: "owner@mindmarket.test",
    plan: "free",
    subscription: null,
    plans: [
      { plan: "free", label: "Free", price_usd_per_month: 0, monthly_analysis: 2, monthly_chat: 2 },
      { plan: "basic", label: "Basic", price_usd_per_month: 10, monthly_analysis: 30, monthly_chat: 100 },
      { plan: "pro", label: "Pro", price_usd_per_month: 25, monthly_analysis: 100, monthly_chat: 300 },
    ],
  },
  error: null,
  meta: { request_id: "r" },
};

function anon() {
  useAuthMock.mockReturnValue({
    user: null,
    accessToken: null,
    loading: false,
    configured: true,
    signIn: vi.fn(),
    signUp: vi.fn(),
    signOut: vi.fn(),
  });
}

function authedFree() {
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
  searchMock.mockReturnValue({ get: () => null });
});

describe("PricingPage", () => {
  it("anonymous → Subscribe routes to /signup", async () => {
    anon();
    // No /billing/me fetch (disabled when accessToken missing); fall
    // back to the static plan catalogue.
    renderWithQuery(<PricingPage />);
    const user = userEvent.setup();
    // Both paid plans show "Sign up to subscribe" when anonymous; any
    // click routes to /signup (no per-plan distinction until the user
    // has an account).
    const ctas = screen.getAllByRole("button", {
      name: /sign up to subscribe/i,
    });
    expect(ctas).toHaveLength(2);
    await user.click(ctas[0]);
    expect(pushMock).toHaveBeenCalledWith("/signup");
  });

  it("authed → Subscribe Basic posts to /checkout_session + redirects to Stripe URL", async () => {
    authedFree();
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(mockJson(BILLING_FREE))
      .mockResolvedValueOnce(
        mockJson({
          data: {
            checkout_url: "https://checkout.stripe.com/c/pay/cs_test_abc",
            session_id: "cs_test_abc",
          },
          error: null,
          meta: { request_id: "r" },
        }),
      );

    // Replace window.location with a plain object so tests can read
    // the assigned href without JSDOM trying to navigate.
    const original = window.location;
    // @ts-expect-error — JSDOM allows the delete here.
    delete window.location;
    // @ts-expect-error — assign a minimal stand-in.
    window.location = { href: "" };

    try {
      const user = userEvent.setup();
      renderWithQuery(<PricingPage />);

      await user.click(
        await screen.findByRole("button", { name: /subscribe to basic/i }),
      );

      await waitFor(() => {
        const call = fetchSpy.mock.calls.find((c) =>
          String(c[0]).includes("/checkout_session"),
        );
        expect(call).toBeDefined();
      });
      await waitFor(() =>
        expect(window.location.href).toBe(
          "https://checkout.stripe.com/c/pay/cs_test_abc",
        ),
      );
    } finally {
      // @ts-expect-error — restore original.
      window.location = original;
    }
  });

  it("renders error copy when /checkout_session fails", async () => {
    authedFree();
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(mockJson(BILLING_FREE))
      .mockResolvedValueOnce(
        mockJson(
          {
            data: null,
            error: { code: "stripe_error", message: "Stripe call failed." },
            meta: { request_id: "r" },
          },
          { status: 502 },
        ),
      );

    const user = userEvent.setup();
    renderWithQuery(<PricingPage />);

    await user.click(
      await screen.findByRole("button", { name: /subscribe to basic/i }),
    );
    expect(
      await screen.findByText(/could not start checkout/i),
    ).toBeInTheDocument();
  });

  it("authed Basic → Basic card shows Current and is disabled", async () => {
    authedFree();
    const basicMe = {
      ...BILLING_FREE,
      data: {
        ...BILLING_FREE.data,
        plan: "basic",
        subscription: {
          stripe_customer_id: "cus_x",
          stripe_subscription_id: "sub_x",
          plan: "basic",
          status: "active",
          current_period_start: null,
          current_period_end: null,
          cancel_at_period_end: false,
        },
      },
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(mockJson(basicMe));

    renderWithQuery(<PricingPage />);
    const currentButton = await screen.findByRole("button", {
      name: /current plan/i,
    });
    expect(currentButton).toBeDisabled();
  });

  it("shows cancellation banner when query has ?checkout=cancelled", async () => {
    authedFree();
    searchMock.mockReturnValue({
      get: (k: string) => (k === "checkout" ? "cancelled" : null),
    });
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(mockJson(BILLING_FREE));

    renderWithQuery(<PricingPage />);
    expect(
      await screen.findByText(/checkout cancelled/i),
    ).toBeInTheDocument();
  });
});
