import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

type AuthState = { user: { id: string } | null; configured: boolean; loading: boolean };
const authMock = vi.fn((): AuthState => ({ user: null, configured: true, loading: false }));
vi.mock("@/lib/auth-context", () => ({ useAuth: () => authMock() }));
vi.mock("next/navigation", () => ({ usePathname: () => "/" }));
vi.mock("@/lib/analytics", () => ({ track: vi.fn() }));

import { MobileNav } from "./mobile-nav";
import { StickyMobileCTA } from "./sticky-mobile-cta";

beforeEach(() => {
  authMock.mockReturnValue({ user: null, configured: true, loading: false });
});

describe("MobileNav", () => {
  it("toggles an overlay with the shared nav links + anon CTAs", () => {
    render(<MobileNav signedIn={false} />);
    // Closed initially — links not shown.
    expect(screen.queryByRole("link", { name: "Product" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /open menu/i }));
    expect(screen.getByRole("link", { name: "Product" })).toHaveAttribute("href", "/product");
    expect(screen.getByRole("link", { name: "Markets" })).toHaveAttribute("href", "/markets");
    expect(screen.getByRole("link", { name: /get started/i })).toHaveAttribute("href", "/signup");
  });

  it("shows Open dashboard when signed in", () => {
    render(<MobileNav signedIn />);
    fireEvent.click(screen.getByRole("button", { name: /open menu/i }));
    expect(screen.getByRole("link", { name: /open dashboard/i })).toHaveAttribute("href", "/");
    expect(screen.queryByRole("link", { name: /get started/i })).not.toBeInTheDocument();
  });
});

describe("StickyMobileCTA", () => {
  it("anon: shows the demo + signup CTAs", () => {
    render(<StickyMobileCTA />);
    expect(screen.getByRole("link", { name: /free risk check/i })).toHaveAttribute(
      "href",
      "/demo-risk-check",
    );
    expect(screen.getByRole("link", { name: /sign up/i })).toHaveAttribute("href", "/signup");
  });

  it("signed-in: renders nothing", () => {
    authMock.mockReturnValue({ user: { id: "u1" }, configured: true, loading: false });
    const { container } = render(<StickyMobileCTA />);
    expect(container).toBeEmptyDOMElement();
  });
});
