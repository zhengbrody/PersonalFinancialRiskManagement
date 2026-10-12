import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { CopilotResearchPanel } from "./copilot-research";
import { CopilotChangeForm, CopilotChangeResult } from "./copilot-change";
import { copilotResearchSchema } from "@/lib/copilot-research";
import { changeComparisonSchema, emptyChange, hypothesisRequest } from "@/lib/copilot-compare";
import fixture from "@/test-fixtures/copilot-research-hypotheses.json";

const research = copilotResearchSchema.parse(fixture);

describe("hypothesis cards", () => {
  it("separates your assumption, research evidence and model inference", () => {
    const onTest = vi.fn();
    render(<CopilotResearchPanel research={[research]} onTestHypothesis={onTest} />);
    fireEvent.click(screen.getByText("AAPL · available"));
    const user = screen.getByRole("article", { name: "Hypothesis AAPL:h0" });
    expect(within(user).getByText("Your assumption")).toBeVisible();
    expect(within(user).getByText("Threshold met by latest provider value")).toBeVisible();
    expect(within(user).getByText(/Net margin > 15% \(your threshold\)/)).toBeVisible();
    expect(within(user).getByText(/Net margin: 20.0% · available · fmp/)).toBeVisible();
    expect(within(user).getByText(/A dated provider snapshot shows AAPL net margin at or below 15%/)).toBeVisible();
    expect(within(user).getByText(/Financial reporting period unknown/)).toBeVisible();
    const cited = screen.getByRole("article", { name: "Hypothesis AAPL:h1" });
    expect(within(cited).getByText(/Cited source not retrieved or verified/)).toBeVisible();
    const method = screen.getByRole("article", { name: "Hypothesis AAPL:h2" });
    expect(within(method).getByText("MindMarket inference")).toBeVisible();
    expect(within(method).getByText("Model inference (not evidence)")).toBeVisible();
    expect(within(method).getByRole("link", { name: "Aswath Damodaran" })).toHaveAttribute("href", expect.stringMatching(/^https:/));
    fireEvent.click(within(user).getByRole("button", { name: "Test in account comparison" }));
    expect(onTest).toHaveBeenCalledWith(expect.objectContaining({ id: "AAPL:h0", subject: "AAPL" }));
  });

  it("offers no comparison action without a portfolio and rejects forged scope", () => {
    render(<CopilotResearchPanel research={[research]} />);
    fireEvent.click(screen.getByText("AAPL · available"));
    expect(screen.queryByRole("button", { name: "Test in account comparison" })).not.toBeInTheDocument();
    const wrong = structuredClone(fixture);
    wrong.hypotheses[0].evidence_observation_ids = ["method:valuation@v1"];
    expect(copilotResearchSchema.safeParse(wrong).success).toBe(false);
    const tools = structuredClone(fixture) as Record<string, unknown> & { hypotheses: Record<string, unknown>[] };
    tools.hypotheses[0].can_authorize_tools = true;
    expect(copilotResearchSchema.safeParse(tools).success).toBe(false);
  });
});

describe("carrying a hypothesis into the comparison", () => {
  const hypothesis = { id: "AAPL:h0", subject: "AAPL", claim: "I think AAPL net margin is above 15%", pct: "", confirmed: false };

  it("requires the user's own non-zero price change and explicit confirmation", () => {
    expect(hypothesisRequest(undefined)).toEqual({ ok: true, value: undefined });
    expect(hypothesisRequest(hypothesis).ok).toBe(false);
    expect(hypothesisRequest({ ...hypothesis, pct: "-20" }).ok).toBe(false);
    expect(hypothesisRequest({ ...hypothesis, pct: "0", confirmed: true }).ok).toBe(false);
    expect(hypothesisRequest({ ...hypothesis, pct: "-96", confirmed: true }).ok).toBe(false);
    expect(hypothesisRequest({ ...hypothesis, pct: "-20", confirmed: true })).toEqual({ ok: true, value: {
      hypothesis_id: "AAPL:h0", subject: "AAPL", price_change_pct: -20, basis: "user_assumption", user_confirmed: true,
    } });
  });

  it("editing the percentage clears confirmation; removal drops the assumption", () => {
    const onChange = vi.fn();
    render(<CopilotChangeForm draft={{ ...emptyChange, ticker: "AAPL", hypothesis: { ...hypothesis, pct: "-10", confirmed: true } }}
      disabled={false} onChange={onChange} onSubmit={() => {}} />);
    expect(screen.getByText(/The research text is not sent and sets no number/)).toBeVisible();
    fireEvent.change(screen.getByLabelText(/Your assumed AAPL price change/), { target: { value: "-25" } });
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ hypothesis: expect.objectContaining({ pct: "-25", confirmed: false }) }));
    fireEvent.click(screen.getByRole("button", { name: "Remove research assumption" }));
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ hypothesis: undefined }));
  });

  const base = {
    result_id: "11111111-1111-4111-8111-111111111111", portfolio_id: "33333333-3333-4333-8333-333333333333",
    computed_at: "2026-09-06T00:00:00+00:00", snapshot_digest: "x", methodology_version: "reduce-close-v1/v",
    assumptions: { expected_portfolio_id: "33333333-3333-4333-8333-333333333333", ticker: "SGOV", amount: 1000, proceeds: "repay_margin",
      hypothesis: { hypothesis_id: "SGOV:h0", subject: "SGOV", price_change_pct: -10, basis: "user_assumption", user_confirmed: true } },
    price_as_of: "2026-09-04", history_start: "2026-04-16", observations: 100, sources: {},
    baseline: { gross_assets: 13000, net_equity: 8000, cash: 1000, margin: 5000, leverage: 1.625, largest_position_weight: 0.83, annual_volatility: 0.1, var_1d_95_usd: 50, cvar_1d_95_usd: 70 },
    candidate: { gross_assets: 12000, net_equity: 8000, cash: 1000, margin: 4000, leverage: 1.5, largest_position_weight: 0.82, annual_volatility: 0.1, var_1d_95_usd: 45, cvar_1d_95_usd: 60 },
    limitations: [],
  };

  it("shows both sides of a computed scenario and an honest not-computable state", () => {
    const computed = changeComparisonSchema.parse({ ...base, hypothesis_scenario: {
      hypothesis_id: "SGOV:h0", subject: "SGOV", price_change_pct: -10, basis: "user_assumption", status: "computed", reason: null,
      subject_value_baseline: 10000, subject_value_candidate: 9000, baseline_pnl: -1000, candidate_pnl: -900, baseline_equity: 7000, candidate_equity: 7100,
    } });
    const { unmount } = render(<CopilotChangeResult result={computed} disabled={false} onRevise={() => {}} />);
    const region = screen.getByRole("region", { name: "Research assumption scenario" });
    expect(within(region).getByText(/SGOV -10% \(your assumption\)/)).toBeVisible();
    expect(region).toHaveTextContent("P&L -$1,000.00");
    expect(region).toHaveTextContent("P&L -$900.00");
    expect(region).toHaveTextContent("Equity $7,100.00");
    unmount();
    const blocked = changeComparisonSchema.parse({ ...base, hypothesis_scenario: {
      hypothesis_id: "SGOV:h0", subject: "SGOV", price_change_pct: -10, basis: "user_assumption", status: "not_computable", reason: "subject_has_options",
      subject_value_baseline: null, subject_value_candidate: null, baseline_pnl: null, candidate_pnl: null, baseline_equity: null, candidate_equity: null,
    } });
    render(<CopilotChangeResult result={blocked} disabled={false} onRevise={() => {}} />);
    expect(screen.getByText(/Not computable: options on this security are not repriced/)).toBeVisible();
    expect(screen.queryByText(/\$0\.00/)).not.toBeInTheDocument();
  });
});
