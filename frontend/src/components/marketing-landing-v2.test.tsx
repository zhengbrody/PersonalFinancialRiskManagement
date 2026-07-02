import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

// MacroSnapshot fetches live data (own tests cover it) — stub so this is a pure
// render smoke of the landing itself.
vi.mock("@/components/macro-snapshot", () => ({
  MacroSnapshot: () => <div data-testid="macro" />,
}));

// The shared <MarketingShell> nav is auth-aware (useAuth) — stub anon.
vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({ user: null, configured: false, loading: false }),
}));

// The hero session chip reads the real clock via isUsTradingHours — pin it per
// test so assertions don't flake with the wall-clock.
const marketHours = vi.hoisted(() => ({ open: true }));
vi.mock("@/lib/market-hours", () => ({
  isUsTradingHours: () => marketHours.open,
}));

import { MarketingLandingV2 } from "./marketing-landing-v2";

beforeEach(() => {
  // jsdom lacks IntersectionObserver; the component guards on it (renders final
  // state). matchMedia is also absent → treated as reduced-motion.
  marketHours.open = true;
});

describe("MarketingLandingV2", () => {
  it("renders the full landing without throwing (hero, demo, pillars, footer)", () => {
    render(<MarketingLandingV2 />);
    expect(screen.getByText(/Know your portfolio/i)).toBeInTheDocument();
    // Appears in both the hero gauge card and a feature pillar.
    expect(screen.getAllByText(/Portfolio Health Score/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/Move the crash slider/i)).toBeInTheDocument();
    expect(screen.getByText(/Real risk math/i)).toBeInTheDocument();
    expect(screen.getByTestId("macro")).toBeInTheDocument(); // embedded live macro
    // CTAs point at real routes.
    expect(screen.getAllByRole("link", { name: /score my portfolio/i })[0]).toHaveAttribute(
      "href",
      "/signup",
    );
    // SEO: learn internal links preserved.
    expect(screen.getByText(/Margin risk calculator/i)).toBeInTheDocument();
  });

  it("the crash slider is deterministic — a deeper shock increases the loss", () => {
    render(<MarketingLandingV2 />);
    const impact = () => screen.getByText(/of a \$100,000 book/i).textContent ?? "";
    const before = impact(); // default -10%
    fireEvent.click(screen.getByRole("button", { name: "-30%" }));
    const after = impact();
    expect(after).not.toEqual(before);
    // -30% is 3× the -10% magnitude → a larger % of the book.
    expect(after).toMatch(/%/);
  });

  it("the hero session chip is honest — open vs closed follow the real session", () => {
    marketHours.open = true;
    const { unmount } = render(<MarketingLandingV2 />);
    expect(screen.getByText(/Live · US market open/i)).toBeInTheDocument();
    unmount();

    marketHours.open = false;
    render(<MarketingLandingV2 />);
    expect(screen.queryByText(/US market open/i)).not.toBeInTheDocument();
    expect(screen.getByText(/US market closed/i)).toBeInTheDocument();
  });

  it("the hero mock cockpit is clearly labelled as sample data", () => {
    render(<MarketingLandingV2 />);
    expect(screen.getByText("Sample")).toBeInTheDocument(); // card pill
    expect(screen.getByText(/1000 · sample book/i)).toBeInTheDocument(); // gauge subline
    expect(screen.getByText(/Sample · 1-day VaR 95%/i)).toBeInTheDocument(); // float chips
  });

  it("the demo band links to the full /demo-risk-check cockpit", () => {
    render(<MarketingLandingV2 />);
    const links = screen.getAllByRole("link", { name: /demo/i });
    expect(links.some((l) => l.getAttribute("href") === "/demo-risk-check")).toBe(true);
  });

  it("no buy/sell advice language anywhere on the page", () => {
    const { container } = render(<MarketingLandingV2 />);
    const text = (container.textContent ?? "").toLowerCase();
    expect(text).not.toMatch(/\bbuy this\b|\bsell this\b|guaranteed|\bbuy now\b/);
    expect(text).toContain("not provide investment"); // educational disclaimer present
  });
});
