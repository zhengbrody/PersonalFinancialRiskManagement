import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

// MarketingShell is auth-aware (useAuth) — render as an anonymous visitor.
const authMock = vi.fn(() => ({ user: null, configured: true, loading: false }));
vi.mock("@/lib/auth-context", () => ({ useAuth: () => authMock() }));

// notFound() must be intercepted so we can assert the 404 path.
const notFound = vi.fn(() => {
  throw new Error("NEXT_NOT_FOUND");
});
vi.mock("next/navigation", () => ({
  notFound: () => notFound(),
  usePathname: () => "/legal/terms",
}));

import LegalDocPage, { generateStaticParams, generateMetadata } from "./page";

beforeEach(() => {
  authMock.mockReturnValue({ user: null, configured: true, loading: false });
  notFound.mockClear();
});

describe("/legal/[doc]", () => {
  it("renders Terms of Service with content + last-updated", () => {
    render(<LegalDocPage params={{ doc: "terms" }} />);
    expect(screen.getByRole("heading", { level: 1, name: "Terms of Service" })).toBeInTheDocument();
    expect(screen.getByText(/Last updated:/)).toBeInTheDocument();
    expect(screen.getByText(/6\. Acceptable use/)).toBeInTheDocument();
  });

  it("renders Privacy Policy + cross-links to the other docs", () => {
    render(<LegalDocPage params={{ doc: "privacy" }} />);
    expect(screen.getByRole("heading", { level: 1, name: "Privacy Policy" })).toBeInTheDocument();
    // body cross-link to a sibling doc (footer uses the short 'Disclaimer' label, so this is unique)
    expect(screen.getByRole("link", { name: /Financial Disclaimer/ })).toBeInTheDocument();
  });

  it("renders the Disclaimer", () => {
    render(<LegalDocPage params={{ doc: "disclaimer" }} />);
    expect(
      screen.getByRole("heading", { level: 1, name: "Financial Disclaimer" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Not investment advice/)).toBeInTheDocument();
  });

  it("calls notFound() for an unknown doc", () => {
    expect(() => render(<LegalDocPage params={{ doc: "nope" }} />)).toThrow("NEXT_NOT_FOUND");
    expect(notFound).toHaveBeenCalled();
  });

  it("generateStaticParams covers all three docs", () => {
    expect(generateStaticParams()).toEqual([
      { doc: "terms" },
      { doc: "privacy" },
      { doc: "disclaimer" },
    ]);
  });

  it("generateMetadata sets a per-doc title + canonical", () => {
    const m = generateMetadata({ params: { doc: "terms" } });
    expect(String(m.title)).toContain("Terms");
    expect(m.alternates?.canonical).toBe("/legal/terms");
  });
});
