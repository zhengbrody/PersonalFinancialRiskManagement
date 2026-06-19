import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// recharts needs a sized parent jsdom lacks — stub the chart primitives.
vi.mock("recharts", () => {
  const Pass = ({ children }: { children?: React.ReactNode }) => <div>{children}</div>;
  const Noop = () => null;
  return {
    ResponsiveContainer: Pass,
    ComposedChart: Pass,
    Bar: Noop,
    Line: Noop,
    XAxis: Noop,
    YAxis: Noop,
    CartesianGrid: Noop,
    Tooltip: Noop,
    Legend: Noop,
  };
});

import { ResearchCharts } from "./research-charts";

function fin(quarters: Array<{ period: string; revenue: number | null }>) {
  return {
    quarters: quarters.map((q) => ({
      period: q.period,
      revenue: q.revenue,
      gross_margin: 0.4,
      operating_margin: 0.3,
      net_margin: 0.25,
    })),
  } as never;
}

describe("ResearchCharts", () => {
  it("renders the revenue & margin trend with ≥2 quarters", () => {
    render(
      <ResearchCharts
        financials={fin([
          { period: "2024-Q3", revenue: 110e9 },
          { period: "2024-Q4", revenue: 120e9 },
        ])}
      />,
    );
    expect(screen.getByText("Revenue & margin trend")).toBeInTheDocument();
  });

  it("renders nothing with fewer than two quarters", () => {
    const { container } = render(
      <ResearchCharts financials={fin([{ period: "2024-Q4", revenue: 120e9 }])} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing without financials", () => {
    const { container } = render(<ResearchCharts />);
    expect(container).toBeEmptyDOMElement();
  });
});
