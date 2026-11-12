/**
 * Stress Lab panel. The response is a captured REAL engine run
 * (e2e/fixtures/factor-stress.json); tests assert on what the panel says and
 * sends, not on chart pixels (recharts draws nothing in jsdom).
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithQuery } from "@/test-utils";
import fixture from "../../e2e/fixtures/factor-stress.json";

vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({ user: { id: "u-1" }, accessToken: "jwt", loading: false, configured: true }),
}));
vi.mock("@/lib/portfolio-context", () => ({
  usePortfolioContext: () => ({ activePortfolioId: "p-1" }),
}));
vi.mock("@/components/ui/chart-line", () => ({
  TimeSeriesChart: ({ data, ariaLabel }: { data: unknown[]; ariaLabel?: string }) => (
    <div data-testid="time-series-chart" aria-label={ariaLabel}>
      {data.length} points
    </div>
  ),
}));

import { FactorStressLab } from "./factor-stress-lab";

type Body = Record<string, unknown>;
let bodies: Body[] = [];

function serve(data: unknown, status = 200, error: unknown = null) {
  bodies = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {
    bodies.push(JSON.parse(String(init?.body ?? "{}")) as Body);
    return new Response(
      JSON.stringify({ data: status === 200 ? data : null, error, meta: { request_id: "t" } }),
      { status, headers: { "Content-Type": "application/json" } },
    );
  });
}

beforeEach(() => serve(fixture));
afterEach(() => vi.restoreAllMocks());

describe("FactorStressLab", () => {
  it("runs on mount with the default settings and shows the account", async () => {
    renderWithQuery(<FactorStressLab />);
    expect(await screen.findByTestId("stress-lab")).toBeInTheDocument();
    expect(bodies[0]).toEqual({ horizon_weeks: 2, confidence: 0.95, fill_unspecified: true });
    expect(screen.getByText("Net equity")).toBeInTheDocument();
    expect(screen.getByText(/Prices as of/)).toBeInTheDocument();
    // Defaults to the equity crash.
    expect(within(screen.getByTestId("stress-scenario-detail")).getByText(/Equity crash/)).toBeInTheDocument();
  });

  it("selecting a historical scenario shows its path and the no-model cross-check", async () => {
    const user = userEvent.setup();
    renderWithQuery(<FactorStressLab />);
    await screen.findByTestId("stress-lab");
    expect(screen.queryByTestId("stress-episode-path")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /COVID-19 crash/ }));
    const detail = screen.getByTestId("stress-scenario-detail");
    expect(within(detail).getByText(/Factor moves actually realised/)).toBeInTheDocument();
    expect(screen.getByTestId("stress-episode-path")).toBeInTheDocument();
    expect(screen.getByTestId("stress-realised-check")).toHaveTextContent(/actually returned/);
    // Selecting is a view change: no new request.
    expect(bodies).toHaveLength(1);
  });

  it("changing the horizon recalculates; changing the regime does not", async () => {
    const user = userEvent.setup();
    renderWithQuery(<FactorStressLab />);
    await screen.findByTestId("stress-lab");
    await user.click(screen.getByRole("button", { name: "Calm" }));
    expect(bodies).toHaveLength(1);
    await user.click(screen.getByRole("button", { name: "4 weeks" }));
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies[1].horizon_weeks).toBe(4);
  });

  it("converts a custom scenario into engine units and rejects nonsense", async () => {
    const user = userEvent.setup();
    renderWithQuery(<FactorStressLab />);
    await screen.findByTestId("stress-lab");

    await user.click(screen.getByRole("button", { name: "Run my scenario" }));
    expect(screen.getByRole("alert")).toHaveTextContent(/at least one factor/);

    await user.type(screen.getByLabelText("Vol move in × VIX"), "0");
    await user.click(screen.getByRole("button", { name: "Run my scenario" }));
    expect(screen.getByRole("alert")).toHaveTextContent(/above 0/);
    expect(bodies).toHaveLength(1);

    await user.clear(screen.getByLabelText("Vol move in × VIX"));
    await user.type(screen.getByLabelText("Vol move in × VIX"), "2");
    await user.type(screen.getByLabelText("Equity move in %"), "-25");
    await user.type(screen.getByLabelText("Rates move in bp"), "100");
    await user.click(screen.getByRole("button", { name: "Run my scenario" }));
    await waitFor(() => expect(bodies).toHaveLength(2));
    const sent = bodies[1].custom_shocks as Record<string, number>;
    expect(sent.equity).toBeCloseTo(-0.25, 9);
    expect(sent.vol).toBeCloseTo(Math.log(2), 9);
    expect(sent.rates).toBeCloseTo(-0.075, 9); // +100bp at 7.5y duration
    expect(Object.keys(sent).sort()).toEqual(["equity", "rates", "vol"]);
  });

  it("says which holdings are proxied or left out, and never implies beta 1", async () => {
    // The captured run has no proxied/unmodelled holdings (their arrays are
    // empty, so TS infers never[]); widen to build that case.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const data = structuredClone(fixture) as any;
    data.coverage = {
      ...data.coverage,
      modelled_weight: 0.8,
      proxied: ["RDDT"],
      unmodelled: [{ ticker: "NEWCO", weight: 0.2, reason: "no usable price history" }],
    };
    data.exposures[0] = { ...data.exposures[0], source: "sector_proxy:XLK" };
    serve(data);
    renderWithQuery(<FactorStressLab />);
    const notes = await screen.findByTestId("stress-coverage-notes");
    expect(notes).toHaveTextContent(/RDDT: too little price history/);
    expect(notes).toHaveTextContent(/NEWCO \(20%\) could not be modelled and is left out/);
    expect(notes).toHaveTextContent(/not assumed to move with the market/);
    expect(screen.getAllByText("proxy").length).toBeGreaterThan(0);
  });

  it("inspecting a holding explains where its loadings come from", async () => {
    const user = userEvent.setup();
    renderWithQuery(<FactorStressLab />);
    await screen.findByTestId("stress-lab");
    await user.click(screen.getByRole("button", { name: "Inspect NVDA" }));
    expect(screen.getByTestId("stress-holding-detail")).toHaveTextContent(/its own \d+ weeks of returns/);
  });

  it("shows simulation error next to VaR and CVaR", async () => {
    renderWithQuery(<FactorStressLab />);
    const table = await screen.findByTestId("stress-tail-table");
    expect(within(table).getAllByText(/±/).length).toBe(4);
  });

  it("a value that rounds to zero is not shown with a minus sign", async () => {
    renderWithQuery(<FactorStressLab />);
    await screen.findByTestId("stress-lab");
    expect(screen.queryByText("−0%")).not.toBeInTheDocument();
    expect(screen.queryByText("-0%")).not.toBeInTheDocument();
  });

  it("explains a portfolio that cannot be modelled instead of showing zeros", async () => {
    serve(null, 422, { code: "no_modelled_holdings", message: "x" });
    renderWithQuery(<FactorStressLab />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/a year of price history/);
    expect(screen.queryByTestId("stress-lab")).not.toBeInTheDocument();
  });
});
