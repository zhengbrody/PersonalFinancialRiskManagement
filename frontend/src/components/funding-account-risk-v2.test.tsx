import { expect, it } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { fundingAccountRiskSchema } from "@/lib/copilot-funding";
import { parseFundingRiskInputs } from "@/lib/funding-risk-inputs";
import { FundingAccountRisk } from "./funding-account-risk";
import { FundingRiskInputs } from "./funding-risk-inputs";
import v2 from "@/test-fixtures/copilot-account-v2.json";

it("shows not-computable reasons, broken coverage, unknown broker rules and no ranking", () => {
  render(<FundingAccountRisk risk={fundingAccountRiskSchema.parse(v2)} />);
  expect(screen.getAllByLabelText("Not computable")).toHaveLength(3);
  expect(screen.getAllByText(/risk-free rate must be supplied explicitly/).length).toBeGreaterThan(0);
  expect(screen.getAllByText(/stock×1 → uncovered×1/).length).toBe(2);
  expect(screen.getByText(/Buying power and margin requirements: unknown/)).toBeVisible();
  expect(within(screen.getByLabelText("Conditional ranking")).getByText(/No ranking/)).toBeVisible();
  expect(screen.getAllByText("Options still open (model value)")[0].nextSibling).toHaveTextContent("Unknown");
});

it("rejects outcomes that do not share the captured snapshot", () => {
  const value = structuredClone(v2);
  value.scenarios[0].outcomes[1].snapshot_id = "0".repeat(64);
  expect(fundingAccountRiskSchema.safeParse(value).success).toBe(false);
});

it("collects the residual rate and requires an explicit objective confirmation", () => {
  const scenario = { label: "S", rows: [{ ticker: "SPY", price: "1" }] };
  expect(parseFundingRiskInputs([scenario], "", "4", "minimize_funding_gap", true)).toMatchObject({ residual_risk_free_rate: 0.04, objective: "minimize_funding_gap", objective_confirmed: true });
  expect(() => parseFundingRiskInputs([scenario], "", "21")).toThrow(/20%/);
  expect(() => parseFundingRiskInputs([scenario], "", "", "", true)).toThrow(/objective/);
  let last: unknown = null;
  render(<FundingRiskInputs expiry="2027-01-15" disabled={false} requiredSymbols={["SPY"]} onChange={value => { last = value; }} />);
  fireEvent.click(screen.getByLabelText("Include explicit account-wide expiry price scenarios"));
  fireEvent.change(screen.getByLabelText("Scenario 1 price 1"), { target: { value: "5" } });
  fireEvent.change(screen.getByLabelText("Comparison objective"), { target: { value: "preserve_terminal_equity" } });
  expect(last).toMatchObject({ objective: "preserve_terminal_equity", objective_confirmed: false });
  fireEvent.click(screen.getByLabelText("Confirm comparison objective"));
  expect(last).toMatchObject({ objective_confirmed: true });
});
