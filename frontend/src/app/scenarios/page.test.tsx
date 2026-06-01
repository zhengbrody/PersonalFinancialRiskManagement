/**
 * /scenarios — efficient frontier + market-move sweep.
 * recharts is stubbed (no layout in jsdom); we assert the cards, the
 * −30% crash callout, and that both charts received data.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithQuery } from "@/test-utils";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));

const useAuthMock = vi.fn();
vi.mock("@/lib/auth-context", () => ({ useAuth: () => useAuthMock() }));

vi.mock("recharts", () => {
  const Pass = ({ children }: { children?: React.ReactNode }) => <div>{children}</div>;
  const Noop = () => null;
  return {
    ResponsiveContainer: Pass,
    BarChart: Pass,
    ScatterChart: Pass,
    Bar: Pass,
    Scatter: Noop,
    Cell: Noop,
    XAxis: Noop,
    YAxis: Noop,
    CartesianGrid: Noop,
    Tooltip: Noop,
    ReferenceLine: Noop,
  };
});

import ScenariosPage from "./page";

function authed() {
  useAuthMock.mockReturnValue({
    user: { id: "u-1", email: "owner@mindmarket.test" },
    accessToken: "test-jwt",
    loading: false,
    configured: true,
  });
}

function envelope(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

const FRONTIER = {
  data: {
    frontier: [
      { vol: 0.08, ret: 0.04 },
      { vol: 0.12, ret: 0.07 },
      { vol: 0.18, ret: 0.1 },
    ],
    current: { vol: 0.14, ret: 0.06 },
    risk_free_rate: 0.045,
  },
  error: null,
  meta: { request_id: "r-f" },
};

const SCENARIOS = {
  data: {
    total_value: 100000,
    scenarios: [
      { shock_pct: -0.3, pnl_pct: -0.27, portfolio_value: 73000 },
      { shock_pct: 0.0, pnl_pct: 0.0, portfolio_value: 100000 },
      { shock_pct: 0.3, pnl_pct: 0.27, portfolio_value: 127000 },
    ],
  },
  error: null,
  meta: { request_id: "r-s" },
};

beforeEach(() => {
  authed();
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.includes("/risk/efficient_frontier")) return envelope(FRONTIER);
    if (url.includes("/risk/scenarios")) return envelope(SCENARIOS);
    return envelope({ data: { plan: "free", credits: null }, error: null, meta: {} });
  });
});

afterEach(() => {
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

describe("ScenariosPage", () => {
  it("renders both cards, the crash callout, and the charts", async () => {
    renderWithQuery(<ScenariosPage />);

    expect(screen.getByRole("heading", { name: /scenarios/i })).toBeInTheDocument();
    expect(screen.getByText(/if the market moves/i)).toBeInTheDocument();
    expect(screen.getByText(/are you paid for your risk/i)).toBeInTheDocument();

    // Scenario data resolved → crash callout + charts.
    expect(await screen.findByText(/−30% market crash/i)).toBeInTheDocument();
    expect(await screen.findByTestId("scenario-chart")).toBeInTheDocument();
    expect(await screen.findByTestId("frontier-chart")).toBeInTheDocument();
  });
});
