import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
vi.mock("@/lib/auth-context", () => ({ useAuth: () => ({ user: null, configured: false, loading: false }) }));
vi.mock("@/lib/analytics", () => ({ track: vi.fn() }));
import { MarketingLandingV2 } from "./marketing-landing-v2";
import { PRODUCT_FAQS } from "@/lib/product-story";
import { track } from "@/lib/analytics";

describe("public product experience", () => {
  it("leads with the product and working sample, not a live market claim", () => {
    const { container } = render(<MarketingLandingV2 />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Understand your risk before your next move.");
    expect(screen.getByRole("link", { name: /Try a sample portfolio/ })).toHaveAttribute("href", "#sample");
    expect(screen.getAllByRole("link", { name: "Analyze my portfolio" })[0]).toHaveAttribute("href", "/signup?next=%2Fportfolios%2Fnew");
    expect(container.textContent).not.toMatch(/same engine your portfolio|Live · US market|Monte-Carlo paths per run/);
    expect(screen.getByRole("link", { name: "Margin risk calculator" })).toBeInTheDocument();
  });
  it("recalculates an exact before/after and preserves the cash versus debt distinction", () => {
    render(<MarketingLandingV2 />);
    const demo = within(screen.getByRole("region", { name: "Interactive sample portfolio" }));
    expect(demo.getByText("$24,000")).toBeInTheDocument();
    expect(demo.getByText("$21,000")).toBeInTheDocument();
    const loan = () => within(demo.getByRole("row", { name: /Margin loan/ })).getAllByRole("cell").map(c => c.textContent);
    expect(loan()).toEqual(["$20,000", "$20,000"]);
    fireEvent.click(demo.getByRole("radio", { name: "Repay margin" }));
    expect(loan()).toEqual(["$20,000", "$10,000"]);
    expect(demo.getByText("$21,000")).toBeInTheDocument();
    fireEvent.change(demo.getByRole("slider"), { target: { value: "50" } });
    expect(loan()).toEqual(["$20,000", "$0"]);
    expect(demo.getByText("$18,000")).toBeInTheDocument();
    fireEvent.change(demo.getByRole("combobox"), { target: { value: "-30" } });
    expect(demo.getByText("$27,000")).toBeInTheDocument();
    fireEvent.click(demo.getByRole("button", { name: /Reset demo/ }));
    expect(demo.getByRole("slider")).toHaveValue("25");
    expect(demo.getByRole("radio", { name: "Keep as cash" })).toBeChecked();
    expect(demo.getByText("$21,000")).toBeInTheDocument();
  });
  it("keeps assumptions visible in the markup and FAQ schema identical to visible answers", () => {
    const { container } = render(<MarketingLandingV2 />);
    expect(screen.getByText(/not VaR, maximum possible loss/)).toBeInTheDocument();
    const schema = JSON.parse(container.querySelector('script[type="application/ld+json"]')!.textContent!);
    expect(schema.mainEntity).toHaveLength(PRODUCT_FAQS.length);
    for (const faq of PRODUCT_FAQS) expect(schema.mainEntity).toContainEqual({
      "@type": "Question", name: faq.question, acceptedAnswer: { "@type": "Answer", text: faq.answer },
    });
    expect(container.textContent).not.toMatch(/\bbuy now\b|guaranteed|pricing|stripe|credit card|credits|subscribe/i);
  });
  it("records one value-free sample interaction, not every slider movement", () => {
    vi.mocked(track).mockClear();
    render(<MarketingLandingV2 />);
    fireEvent.change(screen.getByRole("slider"), { target: { value: "50" } });
    fireEvent.click(screen.getByRole("radio", { name: "Repay margin" }));
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "-30" } });
    expect(vi.mocked(track).mock.calls.filter(([event]) => event === "demo_interacted")).toEqual([
      ["demo_interacted", { kind: "sample_comparison" }],
    ]);
  });
  it("discloses the distinct signed-in test boundaries without opening a FAQ", () => {
    render(<MarketingLandingV2 />);
    const scope = within(screen.getByRole("region", { name: /Different questions\.\s*Clearly defined tests\./ }));
    expect(scope.getByRole("heading", { name: "Research: test the stock/ETF portion" })).toBeVisible();
    expect(scope.getByText(/Cash and option legs are excluded/)).toBeVisible();
    expect(scope.getByText(/Enter a USD amount/)).toBeVisible();
    expect(scope.getByText(/not historical account VaR or volatility/)).toBeVisible();
    expect(scope.getByText(/A new save requires a capture within 15 minutes/)).toBeVisible();
    expect(scope.getByText(/Saving does not refresh quotes, execute a trade or start automatic monitoring/)).toBeVisible();
    expect(screen.getByText(/Simplified educational model—not the signed-in risk engine/)).toBeVisible();
  });
});
