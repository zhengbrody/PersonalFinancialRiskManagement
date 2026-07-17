/**
 * Free-beta gating (NEXT_PUBLIC_BILLING_ENABLED=false): signed-in billing and
 * quota surfaces stay hidden. The public pricing route is tested separately as
 * a redirect to the product story.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithQuery } from "@/test-utils";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => ({ get: () => null }),
}));

const useAuthMock = vi.fn();
vi.mock("@/lib/auth-context", () => ({ useAuth: () => useAuthMock() }));

import { isBillingEnabled } from "@/lib/billing-flag";
import SettingsPage from "@/app/settings/page";
import { CreditsBadge } from "@/components/credits-badge";

function authed() {
  useAuthMock.mockReturnValue({
    user: { id: "u-1", email: "owner@mindmarket.test" },
    accessToken: "jwt",
    loading: false,
    configured: true,
    signIn: vi.fn(),
    signUp: vi.fn(),
    signOut: vi.fn(),
  });
}

function billingJson() {
  return new Response(
    JSON.stringify({
      data: {
        user_id: "u-1",
        email: "owner@mindmarket.test",
        plan: "free",
        subscription: null,
        plans: [
          { plan: "free", label: "Free", price_usd_per_month: 0, monthly_analysis: 2, monthly_chat: 2 },
        ],
      },
      error: null,
      meta: { request_id: "r" },
    }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
}

beforeEach(() => {
  authed();
  vi.spyOn(globalThis, "fetch").mockResolvedValue(billingJson());
});
afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe("isBillingEnabled", () => {
  it("defaults to enabled and disables only on the literal 'false'", () => {
    vi.unstubAllEnvs();
    expect(isBillingEnabled()).toBe(true);
    vi.stubEnv("NEXT_PUBLIC_BILLING_ENABLED", "false");
    expect(isBillingEnabled()).toBe(false);
    vi.stubEnv("NEXT_PUBLIC_BILLING_ENABLED", "true");
    expect(isBillingEnabled()).toBe(true);
  });
});

describe("free beta — billing disabled", () => {
  beforeEach(() => vi.stubEnv("NEXT_PUBLIC_BILLING_ENABLED", "false"));

  it("settings shows Free Beta copy and no upgrade / manage CTA", async () => {
    renderWithQuery(<SettingsPage />);
    expect(await screen.findByText("Free Beta")).toBeInTheDocument();
    expect(screen.queryByText(/Manage subscription/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Upgrade your plan/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Compare paid plans/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/AI credits/i)).not.toBeInTheDocument();
  });

  it("credits badge renders nothing", () => {
    const { container } = renderWithQuery(<CreditsBadge />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("billing enabled (default) — surfaces still render", () => {
  it("settings still shows the plan + manage card", async () => {
    renderWithQuery(<SettingsPage />);
    expect(await screen.findByText("Current plan")).toBeInTheDocument();
    expect(screen.queryByText("Free Beta")).not.toBeInTheDocument();
  });
});
