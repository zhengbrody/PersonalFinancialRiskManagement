/**
 * Home auth-switch: signed-in → Dashboard, anonymous → MarketingLanding,
 * session-loading → skeleton (no flash of the wrong view).
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

  it("shows neither view while the session is still loading", () => {
    useAuthMock.mockReturnValue({ user: null, loading: true, configured: true });
    render(<Home />);
    expect(screen.queryByText("DASHBOARD_VIEW")).not.toBeInTheDocument();
    expect(screen.queryByText("LANDING_VIEW")).not.toBeInTheDocument();
  });
});
