import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { SampleCockpit } from "./sample-cockpit";

// recharts needs a non-zero layout box in jsdom.
vi.mock("./ui/bar-chart", () => ({
  HorizontalBarChart: () => <div data-testid="bar-chart" />,
}));

describe("SampleCockpit", () => {
  it("defaults to the Balanced book (healthy score) + anchor", () => {
    const { container } = render(<SampleCockpit />);
    expect(container.querySelector("#sample-cockpit")).toBeTruthy();
    expect(screen.getByText("784")).toBeInTheDocument(); // balanced default
    expect(screen.getByText(/Score your own/)).toBeInTheDocument();
  });

  it("toggles to the high-growth book → different score + concentration warning", () => {
    render(<SampleCockpit />);
    expect(screen.getByText("784")).toBeInTheDocument();
    // no concentration warning on the balanced book
    expect(screen.queryByText(/single-theme/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /stress a high-growth/i }));
    expect(screen.getByText("541")).toBeInTheDocument(); // growth book
    expect(screen.queryByText("784")).not.toBeInTheDocument();
    // the growth book surfaces a concentration warning
    expect(screen.getByText(/single-theme/i)).toBeInTheDocument();
  });

  it("recomputes scenario loss when a deeper shock is selected", () => {
    render(<SampleCockpit />);
    const before = screen.getByText(/of a .* book/).textContent ?? "";
    fireEvent.click(screen.getByRole("button", { name: "-30%" }));
    const after = screen.getByText(/of a .* book/).textContent ?? "";
    expect(after).not.toEqual(before);
    expect(after).toMatch(/%/);
  });

  it("keeps the educational, no-advice framing", () => {
    render(<SampleCockpit />);
    expect(screen.getByText(/educational only/i)).toBeInTheDocument();
    expect(screen.getByText(/not live prices/i)).toBeInTheDocument();
  });

  it("explains how each number is computed, linking to the learn guides", () => {
    render(<SampleCockpit />);
    expect(screen.getByText(/How each number is computed/i)).toBeInTheDocument();
    expect(screen.getByText(/no AI, nothing invented/i)).toBeInTheDocument();
    // Every methodology learn link points at a real /learn route.
    const learnLinks = screen
      .getAllByRole("link", { name: /learn more/i })
      .map((l) => l.getAttribute("href"));
    expect(learnLinks.length).toBeGreaterThanOrEqual(5);
    for (const href of learnLinks) expect(href).toMatch(/^\/learn\/[a-z-]+$/);
    expect(learnLinks).toContain("/learn/var-cvar-explained");
    expect(learnLinks).toContain("/learn/stress-testing");
  });
});
