/**
 * Home auth-switch: signed-in → Dashboard, anonymous → MarketingLanding.
 * While the session loads: marketing by default (it's also what the
 * production prerender ships to crawlers — a skeleton here means a
 * content-free homepage), skeleton only when localStorage carries a
 * Supabase session (returning user, dashboard incoming).
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

const useAuthMock = vi.fn();
vi.mock("@/lib/auth-context", () => ({ useAuth: () => useAuthMock() }));
vi.mock("@/components/dashboard", () => ({
  Dashboard: () => <div>DASHBOARD_VIEW</div>,
}));
vi.mock("@/components/marketing-landing", () => ({
  MarketingLanding: () => <div>LANDING_VIEW</div>,
}));

import Home from "./page";

afterEach(() => vi.clearAllMocks());

describe("Home", () => {
  it("shows the marketing landing for anonymous visitors", () => {
    useAuthMock.mockReturnValue({ user: null, loading: false, configured: true });
    render(<Home />);
    expect(screen.getByText("LANDING_VIEW")).toBeInTheDocument();
    expect(screen.queryByText("DASHBOARD_VIEW")).not.toBeInTheDocument();
  });

  it("shows the dashboard for signed-in users", () => {
    useAuthMock.mockReturnValue({
      user: { id: "u-1", email: "a@b.com" },
      loading: false,
      configured: true,
    });
    render(<Home />);
    expect(screen.getByText("DASHBOARD_VIEW")).toBeInTheDocument();
    expect(screen.queryByText("LANDING_VIEW")).not.toBeInTheDocument();
  });

  it("shows marketing (the crawlable default) while loading with no stored session", () => {
    useAuthMock.mockReturnValue({ user: null, loading: true, configured: true });
    render(<Home />);
    expect(screen.getByText("LANDING_VIEW")).toBeInTheDocument();
    expect(screen.queryByText("DASHBOARD_VIEW")).not.toBeInTheDocument();
  });

  it("shows a skeleton while loading when localStorage carries a Supabase session", () => {
    // The runner's localStorage is non-functional (node --localstorage-file
    // quirk), so stub the minimal surface hasStoredSession() reads.
    const original = Object.getOwnPropertyDescriptor(window, "localStorage");
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      value: { length: 1, key: () => "sb-test-ref-auth-token" },
    });
    try {
      useAuthMock.mockReturnValue({ user: null, loading: true, configured: true });
      render(<Home />);
      expect(screen.queryByText("LANDING_VIEW")).not.toBeInTheDocument();
      expect(screen.queryByText("DASHBOARD_VIEW")).not.toBeInTheDocument();
    } finally {
      if (original) Object.defineProperty(window, "localStorage", original);
    }
  });
});
