import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";

type AuthState = { user: { id: string } | null; configured: boolean; loading: boolean };
const authMock = vi.fn((): AuthState => ({ user: null, configured: true, loading: false }));
vi.mock("@/lib/auth-context", () => ({ useAuth: () => authMock() }));
vi.mock("next/navigation", () => ({ usePathname: () => "/" }));
vi.mock("@/lib/analytics", () => ({ track: vi.fn() }));

import { MobileNav } from "./mobile-nav";
import { StickyMobileCTA } from "./sticky-mobile-cta";

function setScrollY(y: number) {
  Object.defineProperty(window, "scrollY", { configurable: true, value: y });
}

beforeEach(() => {
  authMock.mockReturnValue({ user: null, configured: true, loading: false });
  setScrollY(0);
});
afterEach(() => setScrollY(0));

describe("MobileNav", () => {
  it("toggles an overlay with the shared nav links + anon CTAs", () => {
    render(<MobileNav signedIn={false} />);
    // Closed initially — links not shown.
    expect(screen.queryByRole("link", { name: "Product" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /open menu/i }));
    expect(screen.getByRole("link", { name: "Product" })).toHaveAttribute("href", "/product");
    expect(screen.getByRole("link", { name: "Markets" })).toHaveAttribute("href", "/markets");
    expect(screen.getByRole("link", { name: /create risk workspace/i })).toHaveAttribute("href", "/signup");
  });

  it("shows Open Today when signed in", () => {
    render(<MobileNav signedIn />);
    fireEvent.click(screen.getByRole("button", { name: /open menu/i }));
    expect(screen.getByRole("link", { name: /open today/i })).toHaveAttribute("href", "/");
    expect(screen.queryByRole("link", { name: /get started/i })).not.toBeInTheDocument();
  });

  it("exposes an accessible dialog and focuses the first item on open", () => {
    render(<MobileNav signedIn={false} />);
    fireEvent.click(screen.getByRole("button", { name: /open menu/i }));
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAttribute("aria-label", "Site menu");
    // Focus moved into the dialog (first nav link).
    expect(screen.getByRole("link", { name: "Product" })).toHaveFocus();
  });

  it("closes on Escape", () => {
    render(<MobileNav signedIn={false} />);
    fireEvent.click(screen.getByRole("button", { name: /open menu/i }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

describe("StickyMobileCTA", () => {
  it("stays hidden until the first CTA scrolls out of view", () => {
    setScrollY(0); // still looking at the hero
    const { container } = render(<StickyMobileCTA />);
    expect(container).toBeEmptyDOMElement();
  });

  it("reveals the demo + signup CTAs once scrolled past the hero", () => {
    setScrollY(2000); // hero well out of view
    render(<StickyMobileCTA />);
    expect(screen.getByRole("link", { name: /open risk demo/i })).toHaveAttribute(
      "href",
      "/demo-risk-check",
    );
    expect(screen.getByRole("link", { name: /create workspace/i })).toHaveAttribute("href", "/signup");
  });

  it("shows once a scroll event pushes past the threshold", () => {
    render(<StickyMobileCTA />);
    expect(screen.queryByRole("link", { name: /open risk demo/i })).not.toBeInTheDocument();
    act(() => {
      setScrollY(2000);
      window.dispatchEvent(new Event("scroll"));
    });
    expect(screen.getByRole("link", { name: /open risk demo/i })).toBeInTheDocument();
  });

  it("signed-in: renders nothing", () => {
    setScrollY(2000);
    authMock.mockReturnValue({ user: { id: "u1" }, configured: true, loading: false });
    const { container } = render(<StickyMobileCTA />);
    expect(container).toBeEmptyDOMElement();
  });
});
