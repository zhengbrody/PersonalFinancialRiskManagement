import { useState } from "react";
import { expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { FundingRiskInputs } from "./funding-risk-inputs";
import { parseFundingRiskInputs } from "@/lib/funding-risk-inputs";

it("defaults off and keeps enabled incomplete inputs invalid instead of omitting risk silently", () => {
  const changed = vi.fn();
  render(<FundingRiskInputs expiry="2027-01-15" disabled={false} onChange={changed} />);
  expect(changed).toHaveBeenLastCalledWith(null, true);
  fireEvent.click(screen.getByRole("checkbox"));
  expect(changed).toHaveBeenLastCalledWith(null, false);
  expect(screen.getByText(/Common expiry: 2027-01-15/)).toBeVisible();
  fireEvent.change(screen.getByLabelText("Scenario 1 ticker 1"), { target: { value: "spy" } });
  expect(screen.getByLabelText("Scenario 1 ticker 1")).toHaveValue("SPY");
  fireEvent.change(screen.getByLabelText("Scenario 1 price 1"), { target: { value: "0" } });
  expect(changed).toHaveBeenLastCalledWith({ scenarios: [{ label: "Scenario 1", prices: { SPY: 0 } }], annual_borrowing_rate: null, residual_risk_free_rate: null, objective: null, objective_confirmed: false }, true);
  fireEvent.change(screen.getByLabelText("Annual borrowing rate (%)"), { target: { value: "0" } });
  expect(changed.mock.lastCall?.[0].annual_borrowing_rate).toBe(0);
  fireEvent.change(screen.getByLabelText("Annual borrowing rate (%)"), { target: { value: "7.5" } });
  expect(changed.mock.lastCall?.[0].annual_borrowing_rate).toBe(0.075);
  fireEvent.click(screen.getByRole("checkbox"));
  expect(changed).toHaveBeenLastCalledWith(null, true);
});

it("supports bounded scenario and ticker rows without defaulting future prices", () => {
  const changed = vi.fn();
  render(<FundingRiskInputs expiry="2027-01-15" disabled={false} onChange={changed} />);
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "Add ticker to scenario 1" }));
  expect(screen.getByLabelText("Scenario 1 price 2")).toHaveValue(null);
  fireEvent.click(within(screen.getByRole("group", { name: "Price scenario 1" })).getByRole("button", { name: "Remove ticker 2" }));
  expect(screen.queryByLabelText("Scenario 1 price 2")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Add price scenario" }));
  fireEvent.click(screen.getByRole("button", { name: "Add price scenario" }));
  expect(screen.getByRole("button", { name: "Add price scenario" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Remove scenario 3" }));
  expect(screen.getByRole("button", { name: "Add price scenario" })).toBeEnabled();
  expect(changed).toHaveBeenLastCalledWith(null, false);
});

it("rejects missing, negative, nonfinite, duplicate and oversized assumptions", () => {
  const scenario = { label: "Stress", rows: [{ ticker: "spy", price: "100" }] };
  for (const price of ["", " ", "-1", "Infinity", "NaN", "1000001"]) expect(() => parseFundingRiskInputs([{ ...scenario, rows: [{ ticker: "SPY", price }] }], "")).toThrow();
  for (const rate of ["-1", "101", "Infinity", "NaN"]) expect(() => parseFundingRiskInputs([scenario], rate)).toThrow();
  expect(() => parseFundingRiskInputs([{ ...scenario, rows: [...scenario.rows, { ticker: "SPY", price: "1" }] }], "")).toThrow(/Duplicate ticker/);
  expect(() => parseFundingRiskInputs([{ ...scenario, rows: Array(101).fill(scenario.rows[0]) }], "")).toThrow(/100 tickers/);
  expect(() => parseFundingRiskInputs(Array(4).fill(scenario), "")).toThrow(/three/);
});

it("disables editing while the parent calculation is running", () => {
  const changed = vi.fn();
  const view = render(<FundingRiskInputs expiry="2027-01-15" disabled={false} onChange={changed} />);
  fireEvent.click(screen.getByRole("checkbox"));
  view.rerender(<FundingRiskInputs expiry="2027-01-15" disabled onChange={changed} />);
  expect(screen.getByRole("checkbox")).toBeDisabled();
  expect(screen.getByLabelText("Scenario 1 ticker 1")).toBeDisabled();
});


it("prefills known symbol names only and leaves every new scenario price unknown", () => {
  const changed = vi.fn();
  render(<FundingRiskInputs expiry="2027-01-15" disabled={false} onChange={changed} requiredSymbols={["spy", "MSFT", "SPY"]} />);
  fireEvent.click(screen.getByRole("checkbox"));
  expect(screen.getByLabelText("Scenario 1 ticker 1")).toHaveValue("SPY");
  expect(screen.getByLabelText("Scenario 1 ticker 2")).toHaveValue("MSFT");
  expect(screen.getByLabelText("Scenario 1 price 1")).toHaveValue(null);
  expect(changed).toHaveBeenLastCalledWith(null, false);
  fireEvent.click(screen.getByRole("button", { name: "Add price scenario" }));
  expect(screen.getByLabelText("Scenario 2 ticker 1")).toHaveValue("SPY");
  expect(screen.getByLabelText("Scenario 2 price 2")).toHaveValue(null);
});


it("notifies once per input value with an inline parent callback, without a render loop", () => {
  const changed = vi.fn();
  function Parent() {
    const [valid, setValid] = useState(true);
    return <><output>{String(valid)}</output><FundingRiskInputs expiry="2027-01-15" disabled={false} onChange={(value, nextValid) => { changed(value, nextValid); setValid(nextValid); }} /></>;
  }
  render(<Parent />);
  expect(changed).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("checkbox"));
  expect(changed).toHaveBeenCalledTimes(2);
  expect(screen.getByRole("status")).toHaveTextContent("false");
  fireEvent.change(screen.getByLabelText("Scenario 1 ticker 1"), { target: { value: "SPY" } });
  expect(changed).toHaveBeenCalledTimes(2);
  fireEvent.change(screen.getByLabelText("Scenario 1 price 1"), { target: { value: "100" } });
  expect(changed).toHaveBeenCalledTimes(3);
});

it("clears old assumptions when remounted under a new account scope key", () => {
  const changed = vi.fn();
  const view = render(<FundingRiskInputs key="account-a" expiry="2027-01-15" disabled={false} requiredSymbols={["SPY"]} onChange={changed} />);
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.change(screen.getByLabelText("Scenario 1 price 1"), { target: { value: "100" } });
  view.rerender(<FundingRiskInputs key="account-b" expiry="2027-01-15" disabled={false} requiredSymbols={["MSFT"]} onChange={changed} />);
  expect(screen.getByRole("checkbox")).not.toBeChecked();
  expect(changed).toHaveBeenLastCalledWith(null, true);
  fireEvent.click(screen.getByRole("checkbox"));
  expect(screen.getByLabelText("Scenario 1 ticker 1")).toHaveValue("MSFT");
  expect(screen.getByLabelText("Scenario 1 price 1")).toHaveValue(null);
  expect(changed).toHaveBeenLastCalledWith(null, false);
});

it("keeps generated labels distinct after removing an earlier scenario", () => {
  render(<FundingRiskInputs expiry="2027-01-15" disabled={false} onChange={vi.fn()} />);
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "Add price scenario" }));
  fireEvent.click(screen.getByRole("button", { name: "Remove scenario 1" }));
  fireEvent.click(screen.getByRole("button", { name: "Add price scenario" }));
  expect(screen.getByLabelText("Scenario 1 name")).toHaveValue("Scenario 2");
  expect(screen.getByLabelText("Scenario 2 name")).toHaveValue("Scenario 1");
});
