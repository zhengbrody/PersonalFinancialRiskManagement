import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

// MarketingShell is auth-aware (useAuth) — drive it per test.
type AuthState = { user: { id: string } | null; configured: boolean; loading: boolean };
const authMock = vi.fn((): AuthState => ({ user: null, configured: true, loading: false }));
vi.mock("@/lib/auth-context", () => ({ useAuth: () => authMock() }));

import { MarketingShell } from "./marketing-shell";
import ProductPage from "@/app/product/page";
import LearnHubPage from "@/app/learn/page";

beforeEach(() => {
  authMock.mockReturnValue({ user: null, configured: true, loading: false });
});

describe("MarketingShell", () => {
  it("renders body + nav + footer; anon shows Sign in + Get started", () => {
    render(
      <MarketingShell>
        <div>BODY_CONTENT</div>
      </MarketingShell>,
    );
    expect(screen.getByText("BODY_CONTENT")).toBeInTheDocument();
    // Wordmark in both nav and footer.
    expect(screen.getAllByText("MindMarket").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/login");
    expect(screen.getByRole("link", { name: "Get started" })).toHaveAttribute("href", "/signup");
    // Educational disclaimer present (no-advice guarantee).
    expect(screen.getByText(/does not provide investment/i)).toBeInTheDocument();
  });

  it("signed-in shows Open dashboard, not the anon CTAs", () => {
    authMock.mockReturnValue({ user: { id: "u1" }, configured: true, loading: false });
    render(
      <MarketingShell>
        <div>BODY</div>
      </MarketingShell>,
    );
    expect(screen.getByRole("link", { name: "Open dashboard" })).toHaveAttribute("href", "/");
    expect(screen.queryByRole("link", { name: "Get started" })).not.toBeInTheDocument();
  });

  it("minimal variant drops nav links + footer links", () => {
    render(
      <MarketingShell minimal>
        <div>BODY</div>
      </MarketingShell>,
    );
    expect(screen.queryByRole("link", { name: "Product" })).not.toBeInTheDocument();
    expect(screen.getByText(/Back to site/i)).toBeInTheDocument();
  });
});

describe("Product page (restyled)", () => {
  it("renders the hero lede, all four pillars, and the no-invention rule", () => {
    render(<ProductPage />);
    expect(screen.getByText(/source-backed risk cockpit/i)).toBeInTheDocument();
    expect(screen.getByText("Portfolio Health Score")).toBeInTheDocument();
    expect(screen.getByText("AI Copilot")).toBeInTheDocument();
    expect(screen.getByText(/never invent a figure/i)).toBeInTheDocument();
  });
});

describe("Learn hub (restyled)", () => {
  it("renders the lede and a grid of topic links", () => {
    render(<LearnHubPage />);
    expect(screen.getByText(/Plain-English, example-led guides/i)).toBeInTheDocument();
    // 7 topic cards + CTAs + nav/footer links.
    expect(screen.getAllByRole("link").length).toBeGreaterThan(7);
  });
});
