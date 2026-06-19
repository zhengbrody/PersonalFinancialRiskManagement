import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// recharts needs a sized parent jsdom lacks — the real ResponsiveContainer never
// resolves dimensions and leaks its worker (OOM / "Timeout terminating forks
// worker"). Stub the chart primitives, exactly as research-charts.test does.
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

// Stub ONLY what the component needs. CRITICAL: return a STABLE object/`mutate`
// every call — the component's effect depends on `mutate` and calls setEdit, so a
// fresh `vi.fn()` per render causes an infinite render loop → OOM / "Timeout
// terminating forks worker". (Also avoids importing the real queries module.)
vi.mock("@/lib/queries", () => {
  const mutate = vi.fn();
  const state = { mutate, isPending: false, isError: false, data: undefined };
  return { useDcf: () => state };
});

import { ValuationDcf } from "./valuation-dcf";

const asm = (value: number, source_type = "derived") => ({ name: "x", value, source_type });

// A minimal but valid DCF (the consolidated bundle's `dcf` block) exercising the
// WACC build-up, equity bridge, and historical-basis sections.
const DCF = {
  ticker: "AAPL",
  currency: "USD",
  valuation_date: "2024-09-28",
  inputs: {
    ticker: "AAPL",
    projection_years: 5,
    base_revenue: asm(1000),
    revenue_growth: [asm(0.1)],
    operating_margin: [asm(0.3)],
    tax_rate: asm(0.18),
    da_pct_revenue: asm(0.05),
    capex_pct_revenue: asm(0.06),
    nwc_pct_revenue: asm(-0.01),
    wacc: asm(0.09),
    wacc_breakdown: [
      { name: "risk_free_rate", value: 0.04, source_type: "derived" },
      { name: "beta", value: 1.2, source_type: "reported" },
      { name: "cost_of_equity", value: 0.1, source_type: "derived" },
      { name: "cost_of_debt", value: 0.045, source_type: "default" },
      { name: "wacc", value: 0.09, source_type: "derived" },
    ],
    terminal_growth: asm(0.025),
    net_debt: asm(170),
    diluted_shares: asm(1000),
    missing_data: [],
  },
  historical: [
    {
      fiscal_year: "2023",
      revenue: 900,
      revenue_growth: 0.1,
      ebit: 270,
      ebit_margin: 0.3,
      tax_pct_ebit: 0.18,
      da_pct_sales: 0.05,
      capex_pct_sales: 0.06,
      nwc_pct_sales: -0.01,
    },
  ],
  projections: [
    {
      year: 1,
      revenue: 1100,
      revenue_growth: 0.1,
      operating_margin: 0.3,
      ebit: 330,
      nopat: 270,
      da: 55,
      capex: 66,
      change_nwc: -11,
      fcf: 270,
      discount_factor: 0.92,
      pv_fcf: 248,
    },
  ],
  terminal_value: 5000,
  pv_terminal_value: 3200,
  enterprise_value: 3448,
  cash: 100,
  short_term_investments: 50,
  total_debt: 300,
  minority_interest: 20,
  diluted_shares: 1000,
  equity_value: 3278,
  implied_value_per_share: 3.28,
  current_price: 3.0,
  upside_pct: 0.093,
  scenarios: [
    { name: "bear", implied_value_per_share: 2.5 },
    { name: "base", implied_value_per_share: 3.28 },
    { name: "bull", implied_value_per_share: 4.1 },
  ],
  sensitivity: [],
  valid: true,
  warnings: [],
  disclaimer: "Educational only.",
};

describe("ValuationDcf — workbook sections", () => {
  it("renders the WACC build-up, equity bridge, and historical basis from bundle data", () => {
    render(<ValuationDcf ticker="AAPL" data={DCF as never} />);
    expect(screen.getByText("WACC build-up")).toBeInTheDocument();
    expect(screen.getByText("Equity bridge")).toBeInTheDocument();
    expect(screen.getByText("Historical basis")).toBeInTheDocument();
    expect(screen.getByText("Implied share price")).toBeInTheDocument();
    expect(screen.getByText("Cost of equity")).toBeInTheDocument(); // a WACC component label
  });

  it("renders nothing for a null ticker", () => {
    const { container } = render(<ValuationDcf ticker={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders source badges next to assumptions", () => {
    render(<ValuationDcf ticker="AAPL" data={DCF as never} />);
    expect(screen.getByText("Assumptions")).toBeInTheDocument();
    // The asm() fixture labels assumptions source_type "derived" → a badge shows.
    expect(screen.getAllByText("derived").length).toBeGreaterThan(0);
  });

  it("invalid DCF still renders the assumptions editor + lists exact missing fields", () => {
    const invalid = {
      ...DCF,
      valid: false,
      implied_value_per_share: null,
      warnings: ["Insufficient inputs to run the DCF: base_revenue, operating_margin."],
      inputs: {
        ...DCF.inputs,
        missing_data: [
          { dataset: "base_revenue", reason: "empty" },
          { dataset: "operating_margin", reason: "empty" },
        ],
      },
    };
    render(<ValuationDcf ticker="ZZZ" data={invalid as never} />);
    // editor is still there so the user can supply the missing overrides
    expect(screen.getByText("Assumptions")).toBeInTheDocument();
    expect(screen.getByText("DCF not valid with these inputs")).toBeInTheDocument();
    expect(screen.getByText("Missing fields")).toBeInTheDocument();
    expect(screen.getByText(/base revenue — empty/)).toBeInTheDocument();
    // exact missing fields, not a generic message
    expect(screen.getByText(/base_revenue, operating_margin/)).toBeInTheDocument();
  });
});

import type { DcfOverrides } from "@/lib/queries";

describe("DcfOverrides type", () => {
  it("accepts every backend-supported editable field", () => {
    const o: DcfOverrides = {
      base_revenue: 1_000,
      revenue_growth: [0.1],
      operating_margin: 0.2,
      tax_rate: 0.21,
      wacc: 0.09,
      terminal_growth: 0.025,
      da_pct_revenue: 0.04,
      capex_pct_revenue: 0.04,
      nwc_pct_revenue: 0.02,
      net_debt: 100,
      diluted_shares: 1_000,
      projection_years: 5,
    };
    // If any field were missing from the type, this file would not compile.
    expect(Object.keys(o)).toHaveLength(12);
  });
});
