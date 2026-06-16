import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { SampleCockpit } from "./sample-cockpit";

// recharts needs a non-zero layout box in jsdom.
vi.mock("./ui/bar-chart", () => ({
  HorizontalBarChart: () => <div data-testid="bar-chart" />,
}));

describe("SampleCockpit", () => {
  it("renders the deterministic score + anchor", () => {
    const { container } = render(<SampleCockpit />);
    expect(container.querySelector("#sample-cockpit")).toBeTruthy();
    expect(screen.getByText("612")).toBeInTheDocument();
    expect(screen.getByText(/Score your own/)).toBeInTheDocument();
  });

  it("recomputes scenario loss when a deeper shock is selected", () => {
    render(<SampleCockpit />);
    // default -10% impact
    const before = screen.getByText(/of a .* book/).textContent ?? "";
    fireEvent.click(screen.getByRole("button", { name: "-30%" }));
    const after = screen.getByText(/of a .* book/).textContent ?? "";
    // -30% is 3x the -10% default → percentage string must change.
    expect(after).not.toEqual(before);
    expect(after).toMatch(/%/);
  });

  it("keeps the educational, no-advice framing", () => {
    render(<SampleCockpit />);
    expect(screen.getByText(/educational only/i)).toBeInTheDocument();
    expect(screen.getByText(/not live prices/i)).toBeInTheDocument();
  });
});
