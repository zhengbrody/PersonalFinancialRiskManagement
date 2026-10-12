import { afterEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { CopilotFunding } from "./copilot-funding";
import { CopilotFundingPlans } from "./copilot-funding-plans";
import { changeComparisonSchema } from "@/lib/copilot-compare";
import { fundingAccountRiskSchema, fundingResultSchema } from "@/lib/copilot-funding";
import { FundingAccountRisk } from "./funding-account-risk";
import { putFieldLabels } from "@/lib/put-fields";
import fixture from "@/test-fixtures/copilot-funding-risk.json";
const riskFixture = fixture;
const source = changeComparisonSchema.parse(fixture.source);
const envelope = (data: unknown) => new Response(JSON.stringify({ data, error: null, meta: { request_id: "test" } }));
afterEach(() => vi.restoreAllMocks());
function fill() {
  render(<CopilotFunding source={source} token="test" protectedHoldings={fixture.request.protected_holdings} />);
  fireEvent.click(screen.getByText("Compare this reduction with Put funding"));
  Object.entries(putFieldLabels).forEach(([key, label]) => fireEvent.change(screen.getByLabelText(`Funding ${label}`), { target: { value: String(fixture.request.put[key as keyof typeof fixture.request.put]) } }));
  fireEvent.change(screen.getByLabelText("Reduction fees (USD)"), { target: { value: String(fixture.request.sale_fees) } });
  fireEvent.click(screen.getByLabelText("Include explicit account-wide expiry price scenarios"));
  fireEvent.change(screen.getByLabelText("Scenario 1 name"), { target: { value: "Explicit downside" } });
  fireEvent.change(screen.getByLabelText("Scenario 1 price 1"), { target: { value: "80" } });
  fireEvent.change(screen.getByLabelText("Scenario 1 price 2"), { target: { value: "50" } });
  fireEvent.change(screen.getByLabelText("Annual borrowing rate (%)"), { target: { value: "8" } });
  screen.getAllByRole("checkbox").filter(box => !box.closest("section[aria-label=\"Optional account expiry scenarios\"]")).forEach(box => fireEvent.click(box));
  fireEvent.click(screen.getByRole("button", { name: "Compare funding alternatives" }));
}
it("submits explicit account assumptions and displays backend-calculated outcomes", async () => {
  const fetcher = vi.spyOn(globalThis, "fetch").mockResolvedValue(envelope(fixture.result));
  fill();
  await screen.findByLabelText("Account-wide expiry scenarios");
  expect(JSON.parse(String(fetcher.mock.calls[0][1]?.body))).toEqual(fixture.request);
  expect(screen.getByText(/Assumed annual borrowing rate: 8%/)).toBeVisible();
  expect(screen.getAllByText("Net equity after interest")).toHaveLength(3);
  fireEvent.change(screen.getByLabelText("Scenario 1 price 1"), { target: { value: "79" } });
  expect(screen.queryByLabelText("Funding alternatives")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Compare funding alternatives" })).toBeDisabled();
});
it.each(["scope", "price", "rate", "date", "baseline"])("rejects mismatched risk %s", async mismatch => {
  const value = structuredClone(fixture.result);
  if (mismatch === "scope") value.account_risk.portfolio_id = "22222222-2222-4222-8222-222222222222";
  if (mismatch === "price") value.account_risk.scenarios[0].prices.SPY = 51;
  if (mismatch === "rate") { value.account_risk.assumptions.annual_borrowing_rate = 0.09; value.assumptions.risk.annual_borrowing_rate = 0.09; }
  if (mismatch === "date") value.account_risk.captured_at = "2026-09-07T00:00:00Z";
  if (mismatch === "baseline") value.account_risk.scenarios[0].outcomes[0] = value.account_risk.scenarios[0].outcomes[1];
  vi.spyOn(globalThis, "fetch").mockResolvedValue(envelope(value));
  fill();
  await screen.findByRole("alert");
  expect(screen.queryByLabelText("Funding alternatives")).not.toBeInTheDocument();
});
it("retrieves original account-wide evidence in saved funding plans", async () => {
  const result = fundingResultSchema.parse(fixture.result);
  vi.spyOn(globalThis, "fetch").mockResolvedValue(envelope({ plan_id: result.result_id, portfolio_id: result.portfolio_id, confirmed_at: result.computed_at, result: { ...result, receipt: null } }));
  render(<CopilotFundingPlans planId={result.result_id} portfolioId={result.portfolio_id} token="test" />);
  fireEvent.click(screen.getByRole("button", { name: "Retrieve saved funding plan" }));
  await screen.findByText("Verified original funding plan. No holdings or orders changed.");
  fireEvent.click(screen.getByText("Original funding inputs and results"));
  expect(screen.getByLabelText("Account-wide expiry scenarios")).toBeVisible();
  expect(screen.getByText("Explicit downside")).toBeVisible();
});

it("renders the assumed borrowing rate without binary-float noise", () => {
  const risk = fundingAccountRiskSchema.parse({ ...riskFixture.result.account_risk,
    assumptions: { ...riskFixture.result.account_risk.assumptions, annual_borrowing_rate: 0.07 } });
  render(<FundingAccountRisk risk={risk} />);
  expect(screen.getByText(/Assumed annual borrowing rate: 7%\./)).toBeVisible();
  expect(screen.queryByText(/7\.0000/)).not.toBeInTheDocument();
});
