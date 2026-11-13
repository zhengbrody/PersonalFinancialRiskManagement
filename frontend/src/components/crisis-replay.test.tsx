/**
 * Crisis replay and Model accuracy panels, on REAL captured outputs
 * (e2e/fixtures). Tests assert on labels and wording, not chart pixels.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithQuery } from "@/test-utils";
import replay from "../../e2e/fixtures/crisis-replay.json";
import validation from "../../e2e/fixtures/stress-validation.json";

vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({ user: { id: "u-1" }, accessToken: "jwt", loading: false, configured: true }),
}));
vi.mock("@/lib/portfolio-context", () => ({
  usePortfolioContext: () => ({ activePortfolioId: "p-1" }),
}));

import { CrisisReplayPanel } from "./crisis-replay";
import { StressValidationPanel } from "./stress-validation";

function serve(data: unknown, status = 200, error: unknown = null) {
  vi.spyOn(globalThis, "fetch").mockImplementation(
    async () =>
      new Response(
        JSON.stringify({ data: status === 200 ? data : null, error, meta: { request_id: "t" } }),
        { status, headers: { "Content-Type": "application/json" } },
      ),
  );
}

afterEach(() => vi.restoreAllMocks());

describe("CrisisReplayPanel", () => {
  it("labels every holding as observed or reconstructed, and says from what", async () => {
    serve(replay);
    const user = userEvent.setup();
    renderWithQuery(<CrisisReplayPanel />);
    await screen.findByTestId("crisis-replay");
    await user.click(screen.getByRole("button", { name: "Global Financial Crisis" }));
    const rddt = screen.getByTestId("replay-holding-RDDT");
    expect(within(rddt).getByText("Reconstructed")).toBeInTheDocument();
    expect(rddt).toHaveTextContent(/estimated from its own recent loadings, which explain \d+% of its moves/);
    expect(within(rddt).getByText("rough estimate")).toBeInTheDocument();
    const aapl = screen.getByTestId("replay-holding-AAPL");
    expect(within(aapl).getByText("Observed")).toBeInTheDocument();
    expect(aapl).not.toHaveTextContent(/estimated/);
    expect(screen.getByText(/Reconstructed holdings did not trade in this period/)).toBeInTheDocument();
  });

  it("names what is left out instead of dropping it", async () => {
    serve(replay);
    renderWithQuery(<CrisisReplayPanel />);
    const panel = await screen.findByTestId("crisis-replay");
    expect(panel).toHaveTextContent("No price is available for ZZZZQ");
    expect(panel).toHaveTextContent("Option positions are not replayed");
  });

  it("shows an unavailable holding with no invented return", async () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const data = structuredClone(replay) as any;
    const ep = data.episodes.find((e: { id: string }) => e.id === "covid_2020");
    ep.holdings[0] = { ...ep.holdings[0], kind: "unavailable", return_pct: null, contribution_pct: null, loadings_source: null, fit_r2: null };
    ep.coverage = { observed_weight: 0.6, reconstructed_weight: 0.1, unavailable_weight: 0.3 };
    serve(data);
    renderWithQuery(<CrisisReplayPanel />);
    await screen.findByTestId("crisis-replay");
    const row = screen.getByTestId(`replay-holding-${ep.holdings[0].ticker}`);
    expect(within(row).getByText("No data")).toBeInTheDocument();
    expect(row).toHaveTextContent("no prices then and no loadings; left out");
    expect(within(row).getAllByText("—")).toHaveLength(2);
    expect(screen.getAllByRole("img", { name: /30% no data/ }).length).toBeGreaterThan(0);
  });

  it("filters holdings and reports peak stress and correlation change", async () => {
    serve(replay);
    const user = userEvent.setup();
    renderWithQuery(<CrisisReplayPanel />);
    await screen.findByTestId("crisis-replay");
    expect(screen.getByTestId("crisis-peak-stress")).toHaveTextContent("Worst five days");
    expect(screen.getByTestId("crisis-correlation")).toHaveTextContent("Stocks and Treasuries");
    await user.click(screen.getByRole("button", { name: "Global Financial Crisis" }));
    await user.click(screen.getByRole("button", { name: "Reconstructed" }));
    expect(screen.queryByTestId("replay-holding-AAPL")).not.toBeInTheDocument();
    expect(screen.getByTestId("replay-holding-RDDT")).toBeInTheDocument();
  });

  it("explains an empty portfolio", async () => {
    serve(null, 422, { code: "no_priced_holdings", message: "x" });
    renderWithQuery(<CrisisReplayPanel />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/Add stock or fund holdings/);
  });
});

describe("StressValidationPanel", () => {
  it("leads with the error, the bias and the interval shortfall", async () => {
    serve(validation);
    renderWithQuery(<StressValidationPanel />);
    const panel = await screen.findByTestId("stress-validation");
    expect(panel).toHaveTextContent("An out-of-sample test");
    // The 90% range held under 85% of the time: the panel must say it is too narrow.
    expect(panel).toHaveTextContent(/its ranges are too narrow/);
    const models = screen.getByTestId("validation-models");
    expect(models).toHaveTextContent("Seven-factor model");
    expect(models).toHaveTextContent("Assume beta = 1");
  });

  it("shows the hashes and that the content check passed", async () => {
    serve(validation);
    renderWithQuery(<StressValidationPanel />);
    const prov = await screen.findByTestId("validation-provenance");
    expect(prov).toHaveTextContent(validation.content_sha256);
    expect(prov).toHaveTextContent(validation.data.sha256);
    expect(prov).toHaveTextContent("Contents match the report hash");
    expect(screen.queryByText(/do not match its recorded hash/)).not.toBeInTheDocument();
  });

  it("warns loudly when the hash check fails or the model has moved on", async () => {
    serve({ ...validation, hash_verified: false, model_version_current: false });
    renderWithQuery(<StressValidationPanel />);
    await screen.findByTestId("stress-validation");
    expect(screen.getByRole("alert")).toHaveTextContent(/do not match its recorded hash/);
    expect(screen.getByText(/is not the version running now/)).toBeInTheDocument();
    expect(screen.getByTestId("validation-provenance")).toHaveTextContent("MISMATCH");
  });

  it("keeps the hindsight-picked basket out unless asked", async () => {
    serve(validation);
    const user = userEvent.setup();
    renderWithQuery(<StressValidationPanel />);
    const table = await screen.findByTestId("validation-rows");
    const before = within(table).getAllByRole("row").length;
    expect(table).not.toHaveTextContent("picked with hindsight");
    await user.click(screen.getByRole("button", { name: "Show" }));
    expect(table).toHaveTextContent("picked with hindsight");
    expect(within(table).getAllByRole("row").length).toBe(before + validation.conditional.hindsight_rows);
  });

  it("marks outcomes that fell outside the stated range", async () => {
    serve(validation);
    renderWithQuery(<StressValidationPanel />);
    const table = await screen.findByTestId("validation-rows");
    const missed = validation.conditional.rows.filter(
      (r) => r.selection === "rule_based" && !(r.band_low <= r.realised && r.realised <= r.band_high),
    ).length;
    expect(within(table).getAllByText(/missed/).length).toBe(missed);
    expect(missed).toBeGreaterThan(0);
  });
});
