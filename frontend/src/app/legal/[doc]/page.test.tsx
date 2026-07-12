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
  // Next 15: the page is an async server component + params is a Promise, so
  // await the function to get the element, then render it.
  it("renders Terms of Service with content + last-updated", async () => {
    render(await LegalDocPage({ params: Promise.resolve({ doc: "terms" }) }));
    expect(screen.getByRole("heading", { level: 1, name: "Terms of Service" })).toBeInTheDocument();
    expect(screen.getByText(/Last updated:/)).toBeInTheDocument();
    expect(screen.getByText(/6\. Acceptable use/)).toBeInTheDocument();
  });

  it("renders Privacy Policy + cross-links to the other docs", async () => {
    render(await LegalDocPage({ params: Promise.resolve({ doc: "privacy" }) }));
    expect(screen.getByRole("heading", { level: 1, name: "Privacy Policy" })).toBeInTheDocument();
    // body cross-link to a sibling doc (footer uses the short 'Disclaimer' label, so this is unique)
    expect(screen.getByRole("link", { name: /Financial Disclaimer/ })).toBeInTheDocument();
  });

  it("renders the Disclaimer", async () => {
    render(await LegalDocPage({ params: Promise.resolve({ doc: "disclaimer" }) }));
    expect(
      screen.getByRole("heading", { level: 1, name: "Financial Disclaimer" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Not investment advice/)).toBeInTheDocument();
  });

  it("calls notFound() for an unknown doc", async () => {
    await expect(LegalDocPage({ params: Promise.resolve({ doc: "nope" }) })).rejects.toThrow(
      "NEXT_NOT_FOUND",
    );
    expect(notFound).toHaveBeenCalled();
  });

  it("generateStaticParams covers all three docs", () => {
    expect(generateStaticParams()).toEqual([
      { doc: "terms" },
      { doc: "privacy" },
      { doc: "disclaimer" },
    ]);
  });

  it("generateMetadata sets a per-doc title + canonical", async () => {
    const m = await generateMetadata({ params: Promise.resolve({ doc: "terms" }) });
    expect(String(m.title)).toContain("Terms");
    expect(m.alternates?.canonical).toBe("/legal/terms");
  });
});
