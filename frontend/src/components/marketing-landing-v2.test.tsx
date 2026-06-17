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

import { MarketingLandingV2 } from "./marketing-landing-v2";

beforeEach(() => {
  // jsdom lacks IntersectionObserver; the component guards on it (renders final
  // state). matchMedia is also absent → treated as reduced-motion.
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

  it("no buy/sell advice language anywhere on the page", () => {
    const { container } = render(<MarketingLandingV2 />);
    const text = (container.textContent ?? "").toLowerCase();
    expect(text).not.toMatch(/\bbuy this\b|\bsell this\b|guaranteed|\bbuy now\b/);
    expect(text).toContain("not provide investment"); // educational disclaimer present
  });
});
