/**
 * HoldingFactorTable: per-holding factor betas from the risk report. Renders a
 * row per holding with factor-ticker columns, "—" for unestimable cells, and
 * nothing at all when the backend ships no rows (or an older backend omits
 * the field).
 */

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { HoldingFactorTable } from "./risk-report";
import type { RiskReport } from "@/lib/queries";

const asReport = (r: Record<string, unknown>) => r as unknown as RiskReport;

describe("HoldingFactorTable", () => {
  it("renders one row per holding with per-factor betas", () => {
    render(
      <HoldingFactorTable
        report={asReport({
          holding_factor_betas: [
            { ticker: "AAPL", betas: { SPY: 1.3, QQQ: 1.5, GLD: null } },
          ],
        })}
      />,
    );
    expect(screen.getByText("Per-holding factor betas")).toBeInTheDocument();
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("1.30")).toBeInTheDocument();
    expect(screen.getByText("1.50")).toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /QQQ/ })).toBeInTheDocument();
  });

  it("renders nothing when the field is absent", () => {
    const { container } = render(<HoldingFactorTable report={asReport({})} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when there are no rows", () => {
    const { container } = render(
      <HoldingFactorTable report={asReport({ holding_factor_betas: [] })} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
