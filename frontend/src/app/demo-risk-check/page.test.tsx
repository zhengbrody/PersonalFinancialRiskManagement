import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

// recharts needs a sized box in jsdom.
vi.mock("@/components/ui/bar-chart", () => ({
  HorizontalBarChart: () => <div data-testid="bar-chart" />,
}));

const trackMock = vi.fn();
vi.mock("@/lib/analytics", () => ({ track: (...a: unknown[]) => trackMock(...a) }));

// The page now wears <MarketingShell> (auth-aware nav) — stub anon.
vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({ user: null, configured: false, loading: false }),
}));

import DemoRiskCheckPage from "./page";

beforeEach(() => trackMock.mockClear());

describe("DemoRiskCheckPage", () => {
  it("renders the public demo cockpit + CTAs with no auth", () => {
    const { container } = render(<DemoRiskCheckPage />);
    expect(container.querySelector("#sample-cockpit")).toBeTruthy();
    expect(screen.getByRole("heading", { name: /before you add more risk/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /analyze my portfolio/i })).toHaveAttribute("href", "/signup");
    expect(screen.getByRole("link", { name: /research a stock/i })).toHaveAttribute("href", "/research");
  });

  it("fires demo_started with a SAFE payload (no ticker / no $ amounts)", () => {
    render(<DemoRiskCheckPage />);
    const call = trackMock.mock.calls.find((c) => c[0] === "demo_started");
    expect(call).toBeTruthy();
    const payload = JSON.stringify(call?.[1] ?? {});
    // safe: no ticker symbols, no dollar values, no holdings.
    expect(payload).not.toMatch(/\$|NVDA|TSLA|SPY|QQQ|ticker|holdings|portfolio_id/i);
  });
});
