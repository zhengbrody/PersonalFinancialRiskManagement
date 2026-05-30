/**
 * /settings page contract.
 *
 *   1. Anonymous → redirected to /login.
 *   2. Free user → "Compare paid plans" CTA (no Portal button).
 *   3. Paid user → "Open Stripe Portal" → POST /portal_session → redirect.
 *   4. ?checkout=success → welcome banner.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithQuery } from "@/test-utils";

const replaceMock = vi.fn();
const searchMock = vi.fn(
  (): { get: (key: string) => string | null } => ({ get: () => null }),
);
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: replaceMock }),
  useSearchParams: () => searchMock(),
}));

const useAuthMock = vi.fn();
vi.mock("@/lib/auth-context", () => ({
  useAuth: () => useAuthMock(),
}));

import SettingsPage from "./page";

function mockJson(body: unknown, init: { status?: number } = {}) {
  return new Response(JSON.stringify(body), {
    status: init.status ?? 200,
    headers: { "Content-Type": "application/json" },
  });
}

const PLANS = [
  { plan: "free", label: "Free", price_usd_per_month: 0, monthly_analysis: 2, monthly_chat: 2 },
  { plan: "basic", label: "Basic", price_usd_per_month: 10, monthly_analysis: 30, monthly_chat: 100 },
  { plan: "pro", label: "Pro", price_usd_per_month: 25, monthly_analysis: 100, monthly_chat: 300 },
];

function authed(extra: { plan: string; subscription: unknown | null } = { plan: "free", subscription: null }) {
  useAuthMock.mockReturnValue({
    user: { id: "u-1", email: "owner@mindmarket.test" },
    accessToken: "jwt-here",
    loading: false,
    configured: true,
    signIn: vi.fn(),
    signUp: vi.fn(),
    signOut: vi.fn(),
  });
  return {
    data: {
      user_id: "u-1",
      email: "owner@mindmarket.test",
      plan: extra.plan,
      subscription: extra.subscription,
      plans: PLANS,
    },
    error: null,
    meta: { request_id: "r" },
  };
}

afterEach(() => {
  vi.clearAllMocks();
  vi.restoreAllMocks();
  searchMock.mockReturnValue({ get: () => null });
});

describe("SettingsPage", () => {
  it("anonymous → redirected to /login", () => {
    useAuthMock.mockReturnValue({
      user: null,
      accessToken: null,
      loading: false,
      configured: true,
      signIn: vi.fn(),
      signUp: vi.fn(),
      signOut: vi.fn(),
    });
    renderWithQuery(<SettingsPage />);
    expect(replaceMock).toHaveBeenCalledWith("/login");
  });

  it("free user → shows upgrade CTA, no Portal button", async () => {
    const me = authed({ plan: "free", subscription: null });
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(mockJson(me));

    renderWithQuery(<SettingsPage />);
    expect(
      await screen.findByRole("button", { name: /compare paid plans/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /open stripe portal/i }),
    ).not.toBeInTheDocument();
  });

  it("paid user → Open Stripe Portal → POST /portal_session + redirect", async () => {
    const me = authed({
      plan: "basic",
      subscription: {
        stripe_customer_id: "cus_paid",
        stripe_subscription_id: "sub_paid",
        plan: "basic",
        status: "active",
        current_period_start: "2026-05-01T00:00:00Z",
        current_period_end: "2026-06-01T00:00:00Z",
        cancel_at_period_end: false,
      },
    });
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(mockJson(me))
      .mockResolvedValueOnce(
        mockJson({
          data: { portal_url: "https://billing.stripe.com/p/session/x" },
          error: null,
          meta: { request_id: "r" },
        }),
      );

    // Replace window.location with a plain stand-in (same pattern as
    // /pricing test). JSDOM won't try to navigate.
    const original = window.location;
    // @ts-expect-error — JSDOM allows delete here.
    delete window.location;
    // @ts-expect-error — assign a minimal stand-in.
    window.location = { href: "" };

    try {
      const user = userEvent.setup();
      renderWithQuery(<SettingsPage />);

      await user.click(
        await screen.findByRole("button", { name: /open stripe portal/i }),
      );

      await waitFor(() => {
        const call = fetchSpy.mock.calls.find((c) =>
          String(c[0]).includes("/portal_session"),
        );
        expect(call).toBeDefined();
      });
      await waitFor(() =>
        expect(window.location.href).toBe(
          "https://billing.stripe.com/p/session/x",
        ),
      );
    } finally {
      // @ts-expect-error — restore.
      window.location = original;
    }
  });

  it("?checkout=success → welcome banner", async () => {
    const me = authed({ plan: "free", subscription: null });
    searchMock.mockReturnValue({
      get: (k: string) => (k === "checkout" ? "success" : null),
    });
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(mockJson(me));

    renderWithQuery(<SettingsPage />);
    expect(
      await screen.findByText(/welcome to your new plan/i),
    ).toBeInTheDocument();
  });
});
