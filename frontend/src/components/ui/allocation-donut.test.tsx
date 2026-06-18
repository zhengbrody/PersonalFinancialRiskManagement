import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { AllocationDonut } from "./allocation-donut";

describe("AllocationDonut", () => {
  it("renders a legend of slices with percentages + a center label", () => {
    render(
      <AllocationDonut
        slices={[
          { label: "Technology", weight: 0.6 },
          { label: "Energy", weight: 0.4 },
        ]}
        centerTop="5"
        centerSub="holdings"
      />,
    );
    expect(screen.getByText("Technology")).toBeInTheDocument();
    expect(screen.getByText("60%")).toBeInTheDocument();
    expect(screen.getByText("Energy")).toBeInTheDocument();
    expect(screen.getByText("40%")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
    expect(screen.getByText("holdings")).toBeInTheDocument();
  });

  it("rolls slices beyond topN into 'Other'", () => {
    const slices = Array.from({ length: 8 }, (_, i) => ({ label: `S${i}`, weight: 0.125 }));
    render(<AllocationDonut slices={slices} topN={3} />);
    expect(screen.getByText("Other")).toBeInTheDocument();
  });

  it("renders nothing without slices", () => {
    const { container } = render(<AllocationDonut slices={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
