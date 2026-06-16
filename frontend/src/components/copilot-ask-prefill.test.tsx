import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { CopilotAsk } from "./copilot-ask";

// useCopilotAsk hits the network; stub it to an idle mutation.
vi.mock("@/lib/queries", () => ({
  useCopilotAsk: () => ({
    mutate: vi.fn(),
    reset: vi.fn(),
    isPending: false,
    isError: false,
    data: undefined,
    error: null,
  }),
}));

function renderWithQuery(ui: React.ReactElement) {
  const qc = new QueryClient();
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

describe("CopilotAsk prefill", () => {
  it("prefills the ask box from initialQuestion without auto-running", () => {
    renderWithQuery(<CopilotAsk initialQuestion="What are the key risks of holding NVDA?" />);
    const input = screen.getByLabelText("Ask Copilot") as HTMLInputElement;
    expect(input.value).toBe("What are the key risks of holding NVDA?");
    // not auto-run: the send button still reads its idle label
    expect(screen.getByRole("button", { name: "Get answer" })).toBeEnabled();
  });

  it("starts empty with no prefill", () => {
    renderWithQuery(<CopilotAsk />);
    expect((screen.getByLabelText("Ask Copilot") as HTMLInputElement).value).toBe("");
  });
});
