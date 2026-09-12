import { afterEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { CopilotPut } from "./copilot-put";
import fixture from "@/test-fixtures/copilot-put.json";

afterEach(() => vi.restoreAllMocks());
const values = {
  "Put underlying": "SPY", "Put expiry": "2026-10-16", "Strike (USD per share)": "100",
  "Assumed premium (USD per share)": "2", "Assumed underlying price (USD)": "105",
  "Estimated total fees (USD)": "1", "Other cash holds, excluding listed put collateral (USD)": "0",
  "Cash buffer to preserve (USD)": "1000",
};
function fill() {
  fireEvent.click(screen.getByText("Test a cash-secured Put"));
  Object.entries(values).forEach(([label, value]) => fireEvent.change(screen.getByLabelText(label), { target: { value } }));
  screen.getAllByRole("checkbox").forEach(box => fireEvent.click(box));
}
const envelope = (data: unknown) => new Response(JSON.stringify({ data, error: null, meta: { request_id: "test" } }));

it("requires explicit inputs and confirmation; edits discard the result", async () => {
  const fetcher = vi.spyOn(globalThis, "fetch").mockResolvedValue(envelope(fixture));
  render(<CopilotPut token="test" portfolioId={fixture.portfolio_id} />);
  expect(fetcher).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Calculate put scenario", hidden: true })).toBeDisabled();
  fill();
  fireEvent.click(screen.getByRole("button", { name: "Calculate put scenario" }));
  await screen.findByRole("region", { name: "Cash-secured put result" });
  const body = JSON.parse(String(fetcher.mock.calls[0][1]?.body));
  expect(body).toEqual(fixture.assumptions);
  expect(screen.getByText("Cash covered under your confirmed assumptions")).toBeVisible();
  expect(screen.getByText("-$1.00")).toBeVisible();
  fireEvent.change(screen.getByLabelText("Strike (USD per share)"), { target: { value: "110" } });
  expect(screen.queryByRole("region", { name: "Cash-secured put result" })).not.toBeInTheDocument();
  screen.getAllByRole("checkbox").forEach(box => expect(box).not.toBeChecked());
});

it("rejects a result calculated for different terms", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(envelope({
    ...fixture, assumptions: { ...fixture.assumptions, strike: 200 },
  }));
  render(<CopilotPut token="test" portfolioId={fixture.portfolio_id} />);
  fill();
  fireEvent.click(screen.getByRole("button", { name: "Calculate put scenario" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("does not match");
  expect(screen.queryByRole("region", { name: "Cash-secured put result" })).not.toBeInTheDocument();
});
