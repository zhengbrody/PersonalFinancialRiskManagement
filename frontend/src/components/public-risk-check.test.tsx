import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const track = vi.fn();
vi.mock("@/lib/analytics", () => ({ track: (...a: unknown[]) => track(...a) }));

const runCheck = vi.fn();
vi.mock("@/lib/public-risk", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/public-risk")>();
  return { ...mod, runPublicRiskCheck: (...a: unknown[]) => runCheck(...a) };
});

import { PublicRiskCheck } from "./public-risk-check";
import {
  ANON_HANDOFF_STORAGE_KEY,
  ANON_HANDOFF_TTL_MS,
  clearAnonHoldings,
  loadAnonHoldings,
  saveAnonHoldings,
} from "@/lib/public-risk";

const RESULT = {
  concentration: {
    top_ticker: "AAPL",
    top_weight: 0.62,
    hhi: 0.45,
    effective_holdings: 2.2,
    weights: { AAPL: 0.62, MSFT: 0.38 },
  },
  metrics: {
    total_value: 12500,
    annual_volatility: 0.21,
    var_95_1d: 0.021,
    cvar_95_1d: 0.031,
    beta_to_market: 1.12,
  },
  stress: [
    { market_shock_pct: -0.1, est_portfolio_impact_pct: -0.112, est_portfolio_impact_usd: -1400 },
  ],
  provenance: {
    as_of: "2026-06-30",
    observations: 251,
    priced: ["AAPL", "MSFT"],
    missing: [],
    sources: { AAPL: "yfinance", MSFT: "yfinance" },
  },
  disclaimer: "Educational risk analytics — nothing stored, not investment advice.",
};

// jsdom storage is broken under the test runner (known project quirk —
// see page.test.tsx) → stub a Map-backed implementation per test run.
const _localStore = new Map<string, string>();
const _sessionStore = new Map<string, string>();
function storage(store: Map<string, string>) {
  return {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, String(v)),
    removeItem: (k: string) => void store.delete(k),
    clear: () => store.clear(),
    key: (i: number) => Array.from(store.keys())[i] ?? null,
    get length() { return store.size; },
  };
}
Object.defineProperty(window, "localStorage", {
  configurable: true,
  value: storage(_localStore),
});
Object.defineProperty(window, "sessionStorage", {
  configurable: true,
  value: storage(_sessionStore),
});

beforeEach(() => {
  vi.clearAllMocks();
  _localStore.clear();
  _sessionStore.clear();
});

function fill(ticker: string, shares: string, row = 1) {
  fireEvent.change(screen.getByLabelText(`Ticker ${row}`), { target: { value: ticker } });
  fireEvent.change(screen.getByLabelText(`Shares ${row}`), { target: { value: shares } });
}

describe("PublicRiskCheck", () => {
  it("runs a check, renders the limited result set, and fires count-only analytics", async () => {
    runCheck.mockResolvedValue(RESULT);
    render(<PublicRiskCheck />);
    fill("aapl", "10");
    fireEvent.click(screen.getByRole("button", { name: /run risk check/i }));

    await waitFor(() => expect(screen.getByTestId("public-risk-result")).toBeInTheDocument());
    expect(runCheck).toHaveBeenCalledWith([{ ticker: "AAPL", shares: 10 }]);
    expect(screen.getByText(/annual volatility/i)).toBeInTheDocument();
    expect(screen.getByText(/1-day VaR/i)).toBeInTheDocument();
    expect(
      screen.getByText(/save this portfolio and unlock the full risk desk/i),
    ).toBeInTheDocument();

    // Analytics: steps + a coarse holdings_band ONLY — never tickers/shares.
    const payloads = JSON.stringify(track.mock.calls);
    expect(track).toHaveBeenCalledWith("public_check_started");
    expect(track).toHaveBeenCalledWith("public_check_completed", { holdings_band: "1-5" });
    expect(payloads).not.toContain("AAPL");
    expect(payloads).not.toContain("10");
  });

  it("saves the holdings to a 24-hour sessionStorage handoff", async () => {
    runCheck.mockResolvedValue(RESULT);
    render(<PublicRiskCheck />);
    fill("MSFT", "5");
    fireEvent.click(screen.getByRole("button", { name: /run risk check/i }));
    await waitFor(() => expect(screen.getByTestId("public-risk-result")).toBeInTheDocument());
    expect(loadAnonHoldings()).toEqual([{ ticker: "MSFT", shares: "5" }]);
    expect(window.localStorage.getItem(ANON_HANDOFF_STORAGE_KEY)).toBeNull();
    expect(screen.getByText(/browser tab for up to 24 hours/i)).toBeInTheDocument();
  });

  it("rejects non-positive shares client-side", async () => {
    render(<PublicRiskCheck />);
    fill("AAPL", "-3");
    fireEvent.click(screen.getByRole("button", { name: /run risk check/i }));
    expect(await screen.findByText(/positive numbers/i)).toBeInTheDocument();
    expect(runCheck).not.toHaveBeenCalled();
  });

  it("invalidates a result and browser handoff when the input changes", async () => {
    runCheck.mockResolvedValue(RESULT);
    render(<PublicRiskCheck />);
    fill("AAPL", "10");
    fireEvent.click(screen.getByRole("button", { name: /run risk check/i }));
    await screen.findByTestId("public-risk-result");
    fireEvent.change(screen.getByLabelText("Shares 1"), { target: { value: "11" } });
    expect(screen.queryByTestId("public-risk-result")).not.toBeInTheDocument();
    expect(loadAnonHoldings()).toEqual([]);
  });

  it("does not retain the prior result when a rerun fails", async () => {
    runCheck.mockResolvedValueOnce(RESULT).mockRejectedValueOnce(new Error("upstream unavailable"));
    render(<PublicRiskCheck />);
    fill("AAPL", "10");
    fireEvent.click(screen.getByRole("button", { name: /run risk check/i }));
    await screen.findByTestId("public-risk-result");
    fireEvent.click(screen.getByRole("button", { name: /run risk check/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/upstream unavailable/i);
    expect(screen.queryByTestId("public-risk-result")).not.toBeInTheDocument();
  });

  it("imports a broker CSV (ticker + shares only, capped at 10)", async () => {
    render(<PublicRiskCheck />);
    const rows = ["Symbol,Quantity,Average Cost"].concat(
      Array.from({ length: 12 }, (_, i) => `T${i + 1},${i + 1},100`),
    );
    const file = new File([rows.join("\n")], "broker.csv", { type: "text/csv" });
    fireEvent.change(screen.getByLabelText(/broker csv file/i), { target: { files: [file] } });

    await waitFor(() =>
      expect(screen.getByText(/imported the first 10 holdings/i)).toBeInTheDocument(),
    );
    expect(track).toHaveBeenCalledWith("public_check_csv_imported", { holdings_band: "6-10" });
    // avg cost column is deliberately dropped — the check never collects it.
    expect((screen.getByLabelText("Ticker 1") as HTMLInputElement).value).toBe("T1");
  });
});

describe("sessionStorage handoff helpers", () => {
  it("round-trips and clears", () => {
    saveAnonHoldings([{ ticker: "SPY", shares: "3" }]);
    expect(loadAnonHoldings()).toEqual([{ ticker: "SPY", shares: "3" }]);
    clearAnonHoldings();
    expect(loadAnonHoldings()).toEqual([]);
  });

  it("ignores corrupt storage", () => {
    window.sessionStorage.setItem(ANON_HANDOFF_STORAGE_KEY, "{not json");
    expect(loadAnonHoldings()).toEqual([]);
    expect(window.sessionStorage.getItem(ANON_HANDOFF_STORAGE_KEY)).toBeNull();
  });

  it("removes the legacy indefinite localStorage handoff without importing it", () => {
    window.localStorage.setItem(
      ANON_HANDOFF_STORAGE_KEY,
      JSON.stringify([{ ticker: "AAPL", shares: "10" }]),
    );
    expect(loadAnonHoldings()).toEqual([]);
    expect(window.localStorage.getItem(ANON_HANDOFF_STORAGE_KEY)).toBeNull();
  });

  it("expires and clears the handoff after 24 hours", () => {
    saveAnonHoldings([{ ticker: "SPY", shares: "3" }], 1_000);
    expect(loadAnonHoldings(1_000 + ANON_HANDOFF_TTL_MS - 1)).toHaveLength(1);
    expect(loadAnonHoldings(1_000 + ANON_HANDOFF_TTL_MS)).toEqual([]);
    expect(window.sessionStorage.getItem(ANON_HANDOFF_STORAGE_KEY)).toBeNull();
  });

  it("lets the user discard the handoff", async () => {
    runCheck.mockResolvedValue(RESULT);
    render(<PublicRiskCheck />);
    fill("MSFT", "5");
    fireEvent.click(screen.getByRole("button", { name: /run risk check/i }));
    await screen.findByTestId("public-risk-result");
    fireEvent.click(screen.getByRole("button", { name: /discard browser handoff/i }));
    expect(loadAnonHoldings()).toEqual([]);
    expect(screen.queryByTestId("public-risk-result")).not.toBeInTheDocument();
  });
});
